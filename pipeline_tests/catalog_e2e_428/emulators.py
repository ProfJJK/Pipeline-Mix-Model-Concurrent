"""Native CLI emulators behind the ``windows.launch_worker`` seam; no process starts.

The fake launcher repeats every check of the real launcher that does not need a
logon token or Job Object: absolute NUL-free argv, protected code path, genuine
RAM descriptor with its identity/cwd validation, the worker-directory ACL, the
Agy agent contract, the RAM environment and the real Claude project-cache
junction. A thread then stands in for the child. Every reply is computed from
the exact argv the production runner built, so a wrong selector, a missing
policy override or an extra flag changes what the runner observes.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from cochem_pipeline import windows
from cochem_pipeline.inference_policy import CODEX_DISABLED_FEATURES

REAL_TIME = time.time
FILETIME_EPOCH = 116444736000000000
CLAUDE_HELP = '\n'.join((
    'Usage: claude [options] [command] [prompt]',
    '  --tools <tools...>              Specify the list of available tools. Use "" to disable all tools',
    '  --strict-mcp-config             Only use MCP servers from --mcp-config',
    '  --mcp-config <configs...>       Load MCP servers from JSON files or strings',
    '  --setting-sources <sources>     Comma-separated list of setting sources to load',
    '  --disable-slash-commands        Disable all slash commands',
    '  --settings <file-or-json>       Path to a settings JSON file or a JSON string',
    '  --effort <level>                Reasoning effort (low, medium, high, xhigh, max)',
    '')).encode()
AGY_REGISTRY = [f'cli_runner_{index:02d}' for index in range(60)]
FAULTS = {'quota429', 'extra_field', 'close_failure'}


def describe(provider, argv):
    """Classify one native invocation by its exact argv (never by intent)."""
    args = argv[1:]
    model = args[args.index('--model') + 1] if '--model' in args else None
    efforts = [json.loads(args[index + 1].split('=', 1)[1]) for index, arg in enumerate(args[:-1])
               if arg == '-c' and args[index + 1].startswith('model_reasoning_effort=')]
    if args == ['--version']:
        kind = 'version'
    elif provider == 'codex':
        kind = ('mcp' if args[-3:] == ['mcp', 'list', '--json'] else 'features' if args[-2:] == ['features', 'list']
                else 'auth' if args[-2:] == ['login', 'status'] else 'inference' if 'exec' in args and args[-1] == '-'
                else 'unknown')
    elif provider == 'claude':
        kind = ('help' if args[-1:] == ['--help'] else 'auth' if args[-3:] == ['auth', 'status', '--json']
                else 'inference' if '--print' in args else 'unknown')
        if '--effort' in args:
            efforts = [args[args.index('--effort') + 1]]
    else:
        kind = ('auth' if args == ['--output-format', 'json', 'models']
                else 'inference' if '--input-format' in args else 'unknown')
    return dict(provider=provider, kind=kind, model=model, efforts=efforts)


class FakeProcess:
    """Observable surface of windows.WindowsProcess, backed by an emulator thread."""

    def __init__(self, host, record, stdin_fd, stdout_fd, stderr_fd):
        self.host, self.record = host, record
        self.pid = record['pid']
        self.args = list(record['argv'])
        self.creation_time_filetime = FILETIME_EPOCH + int(REAL_TIME() * 10_000_000)
        self.creation_time = windows.filetime_unix_seconds(self.creation_time_filetime)
        self.resource_limits_evidence = {'schema': 'offline-e2e-emulator', 'job_object': 'not_created'}
        self.returncode = None
        self.terminated = False
        self.closed = 0
        self._fds = (stdin_fd, stdout_fd, stderr_fd)
        self._thread = threading.Thread(target=self._run, name=f'e2e-native-{self.pid}', daemon=True)
        self._thread.start()

    def _run(self):
        stdin_fd, stdout_fd, stderr_fd = self._fds
        code = 70
        try:
            chunks = []
            while True:
                try:
                    chunk = os.read(stdin_fd, 65536)
                except (BrokenPipeError, OSError):
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            data = b''.join(chunks)
            self.record.update(stdin_sha256=hashlib.sha256(data).hexdigest(), stdin_bytes=len(data))
            out, err, code = self.host.respond(self.record, data)
            for fd, payload in ((stdout_fd, out), (stderr_fd, err)):
                view = memoryview(payload)
                while view:
                    view = view[os.write(fd, view):]
        except BaseException as exc:  # Surfaced by the test; the runner sees exit 70.
            self.host.errors.append(f'{self.record["provider"]}/{self.record["kind"]}: {type(exc).__name__}: {exc}')
            code = 70
        finally:
            for fd in self._fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self.returncode = code

    def poll(self):
        # Joining here keeps the runner off its 100-500 ms jittered poll sleep.
        self._thread.join(1.0)
        return None if self._thread.is_alive() else self.returncode

    def wait(self, timeout=None):
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True

    def close(self):
        self._thread.join(10)
        self.closed += 1
        if self._thread.is_alive():
            raise windows.WindowsCleanupError('Emulated worker tree did not exit')
        if self.record.get('fault') == 'close_failure':
            raise windows.WindowsCleanupError('Emulated worker tree/profile cleanup could not be verified')


class NativeHost:
    """Owns the emulated provider binaries for one temporary installation."""

    def __init__(self, *, executables, versions, profiles_root):
        self.providers = {os.path.normcase(str(path)): name for name, path in executables.items()}
        self.versions = dict(versions)
        self.profiles_root = Path(profiles_root)
        self.launches = []
        self.errors = []
        self.faults = {}
        self.before_launch = None
        self.processes = []
        self._lock = threading.Lock()
        self._pids = itertools.count(41001)

    def launch_worker(self, identity, argv, cwd, stdin_file, stdout_file, stderr_file,
                      env_overrides=None, *, limits=None, ramdisk_workspace=None, agent_definition=None):
        from cochem_pipeline.agy_agent_guard import validate_contract
        from cochem_pipeline.ramdisk import RamWorkspace, exclude_tree_from_indexing
        if not argv or any(not isinstance(arg, str) or '\x00' in arg for arg in argv) or not Path(argv[0]).is_absolute():
            raise ValueError('Worker argv must begin with an absolute native executable and contain no NULs')
        windows.validate_code_path(argv[0])
        if not isinstance(ramdisk_workspace, RamWorkspace):
            raise windows.WindowsIsolationError('RAM execution requires a verified workspace descriptor')
        directory = Path(os.path.abspath(cwd))
        ramdisk_workspace.validate(identity=identity.name, cwd=directory)
        windows._validate_worker_directory(directory, windows._sid_text(windows._account_sid(identity.name)))
        provider = self.providers.get(os.path.normcase(argv[0]))
        if provider is None:
            raise AssertionError('Runner launched an executable outside the emulated installation')
        if env_overrides or limits is None or (agent_definition is not None) != (provider == 'gemini'):
            raise AssertionError('Runner launch options differ from the reviewed native contract')
        if agent_definition is not None:
            validate_contract(agent_definition)
        if not all(hasattr(stream, 'fileno') for stream in (stdin_file, stdout_file, stderr_file)):
            raise AssertionError('Runner must supply owned standard handles')
        profile = self.profiles_root / identity.name
        profile.mkdir(parents=True, exist_ok=True)
        # Real launch_worker: RAM environment, cache binding and indexing exclusion
        # are applied with the profile loaded, before any child exists.
        environment = ramdisk_workspace.environment()
        cache = ramdisk_workspace.bind_native_caches(profile)
        exclude_tree_from_indexing(ramdisk_workspace.root)
        record = dict(describe(provider, list(argv)), argv=list(argv), cwd=str(directory), identity=identity.name,
                      slot=ramdisk_workspace.slot, workspace_root=str(ramdisk_workspace.root), profile=str(profile),
                      scratch_environment=sorted(environment), cache_bound=cache.get('enabled') is True,
                      pid=next(self._pids), real_started_at=REAL_TIME())
        target = (provider, record['model'], record['efforts'][0] if record['efforts'] else None)
        record['fault'] = self.faults.get(target) if record['kind'] == 'inference' else None
        if self.before_launch is not None:
            self.before_launch(record)
        fds = [os.dup(stream.fileno()) for stream in (stdin_file, stdout_file, stderr_file)]
        with self._lock:
            self.launches.append(record)
            process = FakeProcess(self, record, *fds)
            self.processes.append(process)
        return process

    def respond(self, record, stdin):
        provider, kind, argv = record['provider'], record['kind'], record['argv']
        if kind == 'version':
            return (self.versions[provider] + '\n').encode(), b'', 0
        if kind == 'unknown':
            raise AssertionError('Emulator has no reviewed reply for this argv')
        reply = getattr(self, '_' + provider)
        return reply(record, kind, argv, stdin)

    def _codex(self, record, kind, argv, stdin):
        if kind == 'mcp':
            disabled = any(arg.startswith('mcp_servers={') and '"cochem-pipeline"={enabled=false}' in arg for arg in argv)
            servers = [{'name': 'cochem-pipeline', 'enabled': not disabled,
                        'transport': {'type': 'stdio', 'command': 'DO_NOT_LOG', 'env': {'TOKEN': 'DO_NOT_LOG'}}}]
            return json.dumps(servers).encode(), b'', 0
        if kind == 'features':
            lines = [f'{name:<36} stable      {"false" if "features." + name + "=false" in argv else "true"}'
                     for name in (*CODEX_DISABLED_FEATURES, 'undo', 'web_search_request')]
            return ('\n'.join(lines) + '\n').encode(), b'', 0
        if kind == 'auth':
            return b'Logged in using ChatGPT\n', b'', 0
        sandbox = argv[argv.index('--sandbox') + 1] if '--sandbox' in argv else None
        if ('--cd' in argv or '-C' in argv or record['cwd'] != record['workspace_root'] or sandbox != 'read-only'
                or len(record['efforts']) != 1 or not stdin
                or any('features.' + name + '=false' not in argv for name in CODEX_DISABLED_FEATURES)):
            return b'', b'error: emulated codex refused an unreviewed invocation\n', 2
        text = '{"ready":true,"extra":"unrequested"}' if record['fault'] == 'extra_field' else '{"ready":true}'
        thread = 'codex-thread-' + uuid.uuid4().hex
        events = [{'type': 'thread.started', 'thread_id': thread}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'agent_message', 'text': text}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 31, 'cached_input_tokens': 0, 'output_tokens': 7}}]
        return ''.join(json.dumps(event) + '\n' for event in events).encode(), b'', 0

    def _claude(self, record, kind, argv, stdin):
        if kind == 'help':
            return CLAUDE_HELP, b'', 0
        profile = Path(record['profile'])
        if kind == 'auth':
            status = {'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty',
                      'subscriptionType': 'max', 'projectsDirectory': str(profile / '.claude' / 'projects'),
                      'configDirectory': str(profile / '.claude')}
            return json.dumps(status).encode(), b'', 0
        settings = json.loads(argv[argv.index('--settings') + 1])
        if (argv[argv.index('--tools') + 1] != '' or settings.get('alwaysThinkingEnabled') is not True
                or len(record['efforts']) != 1 or not stdin):
            return b'', b'error: emulated claude refused an unreviewed invocation\n', 2
        session = str(uuid.uuid4())
        if record['fault'] == 'quota429':
            envelope = {'type': 'result', 'subtype': 'success', 'is_error': True, 'api_error_status': 429,
                        'duration_ms': 431, 'session_id': session,
                        'result': 'API Error: 429 {"type":"error","error":{"type":"rate_limit_error",'
                                  '"message":"Claude usage limit reached"}}'}
            return json.dumps(envelope).encode(), b'', 1
        result = {'type': 'result', 'subtype': 'success', 'is_error': False, 'duration_ms': 912, 'num_turns': 1,
                  'session_id': session, 'result': '{"ready":true}', 'permission_denials': [],
                  'usage': {'input_tokens': 24, 'output_tokens': 6, 'cache_read_input_tokens': 0,
                            'cache_creation_input_tokens': 0},
                  'modelUsage': {record['model']: {'inputTokens': 24, 'outputTokens': 6}}}
        return json.dumps(result).encode(), b'', 0

    def _gemini(self, record, kind, argv, stdin):
        if kind == 'auth':
            return json.dumps({'status': 'SUCCESS', 'command': {'name': 'models'}}).encode(), b'', 0
        lines = stdin.decode('utf-8').splitlines()
        prompt = json.loads(lines[0]) if len(lines) == 1 else None
        if (not isinstance(prompt, dict) or prompt.get('event') != 'user'
                or argv[argv.index('--agent') + 1] != 'cochem-inference-only'):
            return b'', b'error: emulated agy refused an unreviewed invocation\n', 2
        slug, session = record['model'], 'agy-' + uuid.uuid4().hex
        events = [{'event': 'init', 'conversation_id': session,
                   'init': {'model': slug, 'agent': 'cochem-inference-only', 'tools': AGY_REGISTRY,
                            'permission_mode': 'request-review'}},
                  {'event': 'step_update', 'step_update': {'conversation_id': session, 'step_index': 0,
                                                           'state': 'DONE', 'step_type': 'user_input'}},
                  {'event': 'step_update', 'step_update': {'conversation_id': session, 'step_index': 1,
                                                           'state': 'DONE', 'step_type': 'agent_response',
                                                           'text_delta': '{"ready":true}'}},
                  {'event': 'result', 'result': {'conversation_id': session, 'status': 'SUCCESS',
                                                 'response': '{"ready":true}', 'num_turns': 1,
                                                 'usage': {'input_tokens': 19, 'output_tokens': 5,
                                                           'total_tokens': 24}}}]
        return ''.join(json.dumps(event) + '\n' for event in events).encode(), b'', 0

    def inference(self):
        return [row for row in self.launches if row['kind'] == 'inference']
