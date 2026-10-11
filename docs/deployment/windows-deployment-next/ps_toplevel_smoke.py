"""Top-level plan-mode smoke runner for the deployment .ps1 scripts in this workspace (Windows PowerShell 5.1).

Why: the AST harnesses (test_retarget_warden_r5.py, test_stop_warden_r5.py, ...) dot-source single functions and never run a
script's real top level, so a bug that only exists there - the real param block, real binding, script-scope parameter
variables that keep their [Validate*] attributes, the real main dispatch - stays invisible. The 2026-10-11 17:22 sitting
died on exactly that: retarget-warden-r5.ps1 assigned '' to the [ValidatePattern] parameter variable $script:SourceAttempt.
This module runs the REAL script file top level, in PLAN MODE ONLY, with the host stubbed.

How a run works
  run_toplevel() refuses any argument list that could bind -Apply (every dash spelling and prefix, -Apply:$false included),
  writes a bootstrap, a C# shim and a JSON spec into a fresh temporary directory (never into this workspace) and starts
      powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command
          "$ProgressPreference='SilentlyContinue'; . '<tmp>\\bootstrap.ps1' '<tmp>\\spec.json'; exit $global:PsSmokeExit"
  The bootstrap (dot-sourced at global scope) then
    1. refuses an elevated token, anything but Windows PowerShell 5.1, and (again) any argument that binds -Apply or one
       of its aliases;
    2. defines GLOBAL proxy functions for every host-touching command (functions take precedence over cmdlets). Their
       param blocks are generated from the real cmdlet metadata (names, aliases, parameter sets, positions, Mandatory and
       Validate* kept; types relaxed to [object] except switches), so the target binds against them exactly as it binds
       against the real cmdlets. Stubbed: Test-Path, Get-Item, Get-ChildItem, Get-Content, Get-FileHash, Get-Acl,
       Resolve-Path (file system policy below), Get-CimInstance, Invoke-CimMethod, Get-WmiObject, Get-Process,
       Get-NetTCPConnection, Test-NetConnection, Get-ScheduledTask, Get-ScheduledTaskInfo, Invoke-RestMethod,
       Invoke-WebRequest, Start-Sleep (never sleeps; a budget), Import-Module (no-op for in-box modules), New-Object
       (-ComObject Schedule.Service is a fake Task Scheduler whose GetTask answers per stub; every other COM object and
       host-capable .NET type is denied) and Add-Type (recorded pass-through);
    3. installs a command-lookup guard ($ExecutionContext.InvokeCommand.Pre/PostCommandLookupAction) that is active only
       while the target runs: native executables are answered by the stub's 'natives' rules or DENIED; a module-qualified
       call to a stubbed cmdlet is redirected to its stub; any other cmdlet outside a small pure allow list
       (PURE_CMDLETS: ConvertTo-Json, Where-Object, Join-Path, ...), any module function (CDXML cmdlets such as
       Stop-ScheduledTask) and any other external script is DENIED: it is recorded in the trace and replaced by a block
       that throws 'SmokeDenied: ...' - nothing is executed. The guard is self-tested under StrictMode Latest before the
       target starts and its handlers are checked to be intact afterwards;
    4. replaces two .NET types for the target by user type accelerators: [IO.File] (reads obey the file system policy,
       every write throws SmokeDenied) and [Security.Principal.WindowsPrincipal] (IsInRole(Administrator) answers the
       stub's host.elevated, default False). $env:COMPUTERNAME is set from the stub (default AETHERDESK);
    5. invokes the target with its exact argument array in a nested pipeline of the same runspace:
         invocation='file' (default; what RUN_427_R5_SITTING.ps1 does: powershell.exe -File <script> <args>): the raw
           strings are turned into CommandParameter objects with the Windows PowerShell 5.1 -File algorithm ('-Name' ->
           named, '-Name:value' -> named with the string value, '-Name:' + next -> named, anything else positional; no
           $true/$false conversion) and run like the console host does (script dot-sourced into the global scope).
         invocation='command' (the owner typing at a console): '& <script> <args>' where '-Name' tokens stay parameter
           tokens and every value is a single-quoted literal ($true, $false, $null and integers stay verbatim); when the
           script is stopped by an error the console line's $? is False and that error is reported as the terminating
           one (exit 1), as 'powershell.exe -Command' would;
    6. prints the target's output to stdout and its errors to stderr, and writes result.json: exit code (0 completed,
       1 terminating error, N for an explicit 'exit N'), the terminating error (FullyQualifiedErrorId, category,
       exception type and chain, message, script line), non-terminating errors, self-test facts and the ordered trace.

File system policy (cmdlet stubs and the [IO.File] shim agree)
  A path under stub['fs']['read_roots'] (default: this workspace, the pipeline repo's scripts directory, $PSHOME and the
  target's own directory) is read for real, read-only. stub['fs']['virtual_files'] {path: text} exist with that content;
  stub['fs']['virtual_dirs'] and every ancestor of a virtual path or read root exist as empty-ish directories. Every other
  path is ABSENT. Virtual items carry no readable ACL (Get-Acl fails with SmokeVirtualAcl), so every reviewed protected
  read (Read-R3Control / Assert-ProtectedPath) holds deterministically before .NET opens anything. Registry, certificate
  and WSMan paths are denied. Nothing under C:\\Program Files or C:\\ProgramData is read unless a caller adds a read root.

Stub definition (a dict; default_stub() returns a fresh copy of the 2026-10-11 AETHERDESK world, seen unelevated)
  host:      computer_name, user (owner of processes the unelevated token may inspect), elevated (pretend; the real
             token must not be elevated), last_boot_utc
  fs:        read_roots [paths], virtual_dirs [paths], virtual_files {path: text}
  processes: [{pid, parent_pid, name, path, command_line, owner ('DOMAIN\\user' or None), created_utc, session_id,
             visible_unelevated}]  - unelevated, ExecutablePath/CommandLine/GetOwner of another owner's process are not
             readable unless visible_unelevated is true, exactly like Win32_Process
  listeners: [{port, pid, address}]  - Get-NetTCPConnection answers CmdletizationQuery_NotFound when nothing matches
  tasks:     {'*': default, name: 'denied' | 'absent' | {enabled, state, instances, last_task_result, xml, sddl,
             description, principal{user_id, logon_type, run_level}, settings{...}, actions[{path, arguments,
             working_directory}], triggers[{type, enabled, user_id, delay, ...}]}}. Unelevated reality: 'denied'.
             Run/RunEx/Stop, the Enabled setter, RegisterTaskDefinition and every other mutation are always denied.
  natives:   {'robocopy.exe' or a full path (lower case): [{'match': regex over the joined arguments (optional),
             'exit': int, 'stdout': str, 'stderr': str}]}  - a native with no matching rule is DENIED
  http:      {'http://127.0.0.1:47824/health': {'status': 200, 'body': '{...}'}}  - other loopback URLs answer
             'Unable to connect to the remote server'; any non-loopback URL is denied
  sleep_budget: Start-Sleep calls allowed before the run is failed (plan mode should never poll), default 20
  pure_extra:   extra cmdlet names to allow as pure

Use from a harness (always through the heavy-run lock, single process, never -n):
    PY -I W\\serialize-heavy.py --timeout-minutes 120 --label <name> -- PY -I -B -m pytest -p no:cacheprovider -q <files>

    import ps_toplevel_smoke as smoke        # a test file in W imports it directly (pytest prepends W to sys.path)
    stub = smoke.default_stub()
    stub['processes'] = smoke.live_mcp_clients_20261011()          # optional: the 14 owner MCP clients of 17:22
    result = smoke.run_toplevel(smoke.WORKSPACE / 'stop-warden-r5.ps1',
                                ['-Attempt', 'v1', '-RetargetTarget', 'r5', '-RetargetAttempt', 'v1'], stub=stub)
    assert smoke.plan_mode_outcome(result, plan_schema='cochem-warden-stop-plan/2') == 'plan'
    result.plan['controller_presence']                          # the parsed plan
    result.calls('Get-CimInstance'); result.trace; result.denied   # what the script asked the host
  plan_mode_outcome() returns 'plan' (exit 0 and a READ_ONLY_PLAN JSON document) or 'refusal' (exit 1 from the script's
  own 'throw <string>'), and raises HostAccessDenied (a non-stubbed host command was reached), PsVariableValidationError
  (assignment to a validated variable, the 17:22 bug), PsBindingError (any other parameter binding/validation error) or
  PlanModeError (any other engine error, e.g. StrictMode or a null method call). SmokeRefused is raised before any process
  starts for an -Apply argument; SmokeHarnessError when the bootstrap itself could not run.
  Set PS_TOPLEVEL_SMOKE_KEEP=1 (or keep_temp=True) to keep the temporary directory for inspection.

Limits: .NET calls other than [IO.File] and [Security.Principal.WindowsPrincipal] are not intercepted (fully qualified
[System.IO.File] included), so safety also rests on plan mode, the refused -Apply and the unelevated token; the scripts'
hash-pinned helper sources are read for real from the read roots; the real identity name is reported by
WindowsIdentity.GetCurrent().
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

WORKSPACE = Path(__file__).resolve().parent
PIPELINE_SCRIPTS = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts')
PSHOME = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0')
_SYSTEM_DIR = 'System32' if sys.maxsize > 2 ** 32 else 'Sysnative'
POWERSHELL = Path(os.environ.get('SystemRoot', r'C:\Windows')) / _SYSTEM_DIR / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
RESULT_SCHEMA = 'ps-toplevel-smoke-result/1'
DEFAULT_TIMEOUT = 300.0
_DASHES = ('-', '\u2013', '\u2014', '\u2015')

PURE_CMDLETS = (
    'Add-Member', 'Clear-Variable', 'Compare-Object', 'ConvertFrom-Csv', 'ConvertFrom-Json', 'ConvertFrom-StringData',
    'ConvertTo-Csv', 'ConvertTo-Json', 'ConvertTo-Xml', 'ForEach-Object', 'Format-Custom', 'Format-List', 'Format-Table',
    'Format-Wide', 'Get-Culture', 'Get-Date', 'Get-Host', 'Get-Location', 'Get-Member', 'Get-PSCallStack', 'Get-Random',
    'Get-UICulture', 'Get-Unique', 'Get-Variable', 'Group-Object', 'Join-Path', 'Measure-Command', 'Measure-Object',
    'New-Guid', 'New-TimeSpan', 'New-Variable', 'Out-Default', 'Out-Host', 'Out-Null', 'Out-String', 'Remove-Variable',
    'Select-Object', 'Set-StrictMode', 'Set-Variable', 'Sort-Object', 'Split-Path', 'Where-Object', 'Write-Debug',
    'Write-Error', 'Write-Host', 'Write-Information', 'Write-Output', 'Write-Progress', 'Write-Verbose', 'Write-Warning',
)

_STUB_KEYS = {'host', 'fs', 'processes', 'listeners', 'tasks', 'natives', 'http', 'sleep_budget', 'pure_extra'}
_HOST_KEYS = {'computer_name', 'user', 'elevated', 'last_boot_utc'}
_FS_KEYS = {'read_roots', 'virtual_dirs', 'virtual_files'}
_PROCESS_KEYS = {'pid', 'parent_pid', 'name', 'path', 'command_line', 'owner', 'created_utc', 'session_id', 'visible_unelevated'}

_CB = r'C:\Program Files\CoChem'
R4_ROOT = _CB + r'\Pipeline4.2.7-windows-20261009-r4'
R5_ROOT = _CB + r'\Pipeline4.2.7-windows-20261011-r5'
TOOLCHAIN_PYTHON = _CB + r'\Toolchain4.2.7-windows-20261006\Python312\python.exe'
CLIENT_CONFIG = r'C:\Users\ansac\CoChem427\pipeline-client-r3.json'
BRIDGE_CONFIG = r'C:\Users\ansac\CoChem427\bridge.local.json'

_DEFAULT_STUB: dict[str, Any] = {
    'host': {'computer_name': 'AETHERDESK', 'user': 'AETHERDESK\\ansac', 'elevated': False, 'last_boot_utc': '2026-10-10T22:57:00Z'},
    'fs': {
        'read_roots': [str(WORKSPACE), str(PIPELINE_SCRIPTS), str(PSHOME)],
        # The installed trees as of the 2026-10-11 17:22 sitting (r5 beside r4), as an unelevated token sees their names.
        'virtual_dirs': [
            _CB + r'\Pipeline4.2.7-windows-20261007-r3', R4_ROOT, R4_ROOT + r'\.venv\Scripts', R5_ROOT, R5_ROOT + r'\.venv\Scripts',
            _CB + r'\Toolchain4.2.7-windows-20261006\Python312', _CB + r'\WardenCommissioning4.2.7-windows-20261007-r3-v1',
            _CB + r'\WardenRetarget4.2.7-windows-20261010-r4-v1', _CB + r'\WardenConfig4.2.7-windows-20261011-r5-v1',
            _CB + r'\R5Sitting4.2.7-windows-20261011-v1', r'C:\ProgramData\CoChemPipeline427\private',
        ],
        'virtual_files': {
            # Synthetic, never the real file: the client config names only the pinned port and token path.
            CLIENT_CONFIG: '{"port": 47824, "token_file": "C:\\\\Users\\\\ansac\\\\CoChem427\\\\controller.token"}\n',
            TOOLCHAIN_PYTHON: 'smoke-virtual\n', R4_ROOT + r'\.venv\Scripts\python.exe': 'smoke-virtual\n',
            R5_ROOT + r'\.venv\Scripts\python.exe': 'smoke-virtual\n', R4_ROOT + r'\pipeline.json': 'smoke-virtual\n',
            _CB + r'\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json': 'smoke-virtual\n',
            _CB + r'\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json': 'smoke-virtual\n',
        },
    },
    'processes': [],
    'listeners': [],
    'tasks': {'*': 'denied'},
    'natives': {},
    'http': {},
    'sleep_budget': 20,
    'pure_extra': [],
}


class SmokeRefused(RuntimeError):
    """The request is outside plan mode (an -Apply argument) or the host cannot run it safely; nothing was started."""


class SmokeHarnessError(RuntimeError):
    """The bootstrap could not run the target (self-test failure, missing result, timeout)."""


class PlanModeAssertion(AssertionError):
    """Base class of the plan-mode verdicts raised by plan_mode_outcome()."""


class HostAccessDenied(PlanModeAssertion):
    """The target reached a host command that is not stubbed (it was blocked, not executed)."""


class PsBindingError(PlanModeAssertion):
    """A PowerShell parameter binding or validation error escaped the target."""


class PsVariableValidationError(PsBindingError):
    """An assignment to a variable that carries [Validate*]/type metadata failed (ValidationMetadataException)."""


class PlanModeError(PlanModeAssertion):
    """Neither a READ_ONLY_PLAN document nor a clean refusal (an engine error such as StrictMode or a null call)."""


_BINDING_TYPES = {
    'System.Management.Automation.ParameterBindingException',
    'System.Management.Automation.ParameterBindingValidationException',
    'System.Management.Automation.ParameterBindingArgumentTransformationException',
    'System.Management.Automation.ParameterBindingParameterDefaultValueException',
    'System.Management.Automation.ValidationMetadataException',
    'System.Management.Automation.ArgumentTransformationMetadataException',
}
_VARIABLE_TYPES = {
    'System.Management.Automation.ValidationMetadataException',
    'System.Management.Automation.ArgumentTransformationMetadataException',
}
_BINDING_IDS = {
    'MissingMandatoryParameter', 'ParameterArgumentValidationError', 'ParameterArgumentTransformationError',
    'NamedParameterNotFound', 'PositionalParameterNotFound', 'AmbiguousParameterSet', 'AmbiguousParameter',
    'MissingArgument', 'ParameterAlreadyBound', 'ValidateSetFailure', 'ArgumentTransformationMetadataException',
    'CannotConvertArgumentNoMessage', 'CannotConvertArgument', 'ParameterBindingFailed', 'GetDynamicParametersException',
}


@dataclasses.dataclass(frozen=True)
class ErrorInfo:
    fqid: str
    inner_fqid: str
    category: str
    exception_type: str
    chain: tuple[str, ...]
    message: str
    script_name: str
    line: int
    line_text: str

    @classmethod
    def from_json(cls, data: dict | None) -> 'ErrorInfo | None':
        if not data:
            return None
        return cls(fqid=str(data.get('fqid') or ''), inner_fqid=str(data.get('inner_fqid') or ''),
                   category=str(data.get('category') or ''), exception_type=str(data.get('exception_type') or ''),
                   chain=tuple(str(x) for x in (data.get('chain') or [])), message=str(data.get('message') or ''),
                   script_name=str(data.get('script_name') or ''), line=int(data.get('line') or 0),
                   line_text=str(data.get('line_text') or ''))

    @property
    def is_binding(self) -> bool:
        ids = {self.fqid.split(',')[0], self.inner_fqid.split(',')[0]}
        return self.exception_type in _BINDING_TYPES or any(t in _BINDING_TYPES for t in self.chain) or bool(ids & _BINDING_IDS)

    @property
    def variable(self) -> str | None:
        """The variable named by a failed validated-variable assignment, or None."""
        if self.exception_type not in _VARIABLE_TYPES:
            return None
        match = re.search(r'for the (\w+) variable', self.message)
        return match.group(1) if match else '?'

    @property
    def is_clean_refusal(self) -> bool:
        """The script's own 'throw <string>': a RuntimeException in OperationStopped whose error id is the message."""
        same = self.inner_fqid == self.message or self.inner_fqid.startswith(self.message + ',')
        return (self.exception_type == 'System.Management.Automation.RuntimeException' and self.category == 'OperationStopped'
                and same and not self.message.startswith('SmokeDenied'))

    def describe(self) -> str:
        where = f' at {Path(self.script_name).name}:{self.line}' if self.script_name else ''
        return f'{self.exception_type} [{self.fqid}]{where}: {self.message}'


@dataclasses.dataclass(frozen=True)
class SmokeResult:
    script: str
    args: tuple[str, ...]
    invocation: str
    exit_code: int | None
    process_exit_code: int
    stdout: str
    stderr: str
    error: ErrorInfo | None
    errors: tuple[ErrorInfo, ...]
    trace: tuple[dict, ...]
    self_test: dict
    refused: str | None
    bootstrap_error: str | None
    guard_intact: bool | None
    duration_s: float
    temp_dir: str | None

    @property
    def denied(self) -> list[dict]:
        return [entry for entry in self.trace if entry.get('kind') == 'denied']

    @property
    def binding_error(self) -> bool:
        return bool(self.error and self.error.is_binding) or any(e.is_binding for e in self.errors)

    @property
    def plan(self) -> Any:
        """The JSON document the target printed (its read-only plan), or None."""
        text = self.stdout.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            start, end = text.find('{'), text.rfind('}')
            if 0 <= start < end:
                try:
                    return json.loads(text[start:end + 1])
                except ValueError:
                    return None
            return None

    def calls(self, command: str | None = None, kind: str | None = None) -> list[dict]:
        """Trace entries for one command name (case-insensitive) and/or one kind."""
        return [e for e in self.trace if (command is None or str(e.get('command', '')).lower() == command.lower())
                and (kind is None or e.get('kind') == kind)]

    def describe(self) -> str:
        lines = [f'{Path(self.script).name} {" ".join(self.args)} [{self.invocation}] exit={self.exit_code} '
                 f'({self.duration_s:.1f}s)']
        if self.refused:
            lines.append(f'refused: {self.refused}')
        if self.bootstrap_error:
            lines.append(f'bootstrap error: {self.bootstrap_error}')
        if self.error:
            lines.append(f'terminating: {self.error.describe()}')
        for entry in self.denied:
            lines.append(f'DENIED {entry.get("command")}: {entry.get("detail")}')
        if self.stderr.strip():
            lines.append('stderr: ' + self.stderr.strip()[:1500])
        return '\n'.join(lines)

    def raise_for_harness(self) -> None:
        if self.refused:
            raise SmokeRefused(self.refused)
        if self.bootstrap_error or self.exit_code is None:
            raise SmokeHarnessError(self.describe())
        if self.guard_intact is False:
            raise SmokeHarnessError('the command-lookup guard was replaced while the target ran\n' + self.describe())


def default_stub() -> dict:
    """A fresh copy of the default host stub: AETHERDESK on 2026-10-11 after the failed sitting, seen unelevated."""
    return copy.deepcopy(_DEFAULT_STUB)


def live_mcp_clients_20261011() -> list[dict]:
    """The 14 owner MCP client processes alive at the 2026-10-11 17:22 sitting (port 47824 had no listener).

    Ten are 'python -I -B -m cochem_pipeline mcp --client-config ...pipeline-client-r3.json' (Claude Desktop, Codex,
    Antigravity, Claude Code), four are the Antigravity bridge entries 'python -m cochem_mcp --provider codex|claude
    --config ...bridge.local.json'; all run as AETHERDESK\\ansac from the r4 venv or the Toolchain interpreter.
    """
    r4_python = R4_ROOT + r'\.venv\Scripts\python.exe'
    processes = []
    pid = 21000
    for index in range(10):
        image = r4_python if index % 2 == 0 else TOOLCHAIN_PYTHON
        processes.append({'pid': pid, 'parent_pid': 20000 + index, 'name': 'python.exe', 'path': image,
                          'command_line': f'"{image}" -I -B -m cochem_pipeline mcp --client-config {CLIENT_CONFIG}',
                          'owner': 'AETHERDESK\\ansac', 'created_utc': f'2026-10-11T15:{10 + index:02d}:00Z'})
        pid += 4
    for index, provider in enumerate(('codex', 'claude', 'codex', 'claude')):
        image = r4_python if index < 2 else TOOLCHAIN_PYTHON
        processes.append({'pid': pid, 'parent_pid': 20100 + index, 'name': 'python.exe', 'path': image,
                          'command_line': f'"{image}" -m cochem_mcp --provider {provider} --config {BRIDGE_CONFIG}',
                          'owner': 'AETHERDESK\\ansac', 'created_utc': f'2026-10-11T15:{30 + index:02d}:00Z'})
        pid += 4
    return processes


def apply_argument(args: Iterable[str]) -> str | None:
    """The first argument that could bind -Apply (any dash, any prefix of 'apply', with or without ':value'), or None."""
    for arg in args:
        text = str(arg)
        if len(text) < 2 or text[0] not in _DASHES:
            continue
        name = text[1:].split(':', 1)[0].strip()
        if name and 'apply'.startswith(name.lower()):
            return text
    return None


def render_command_text(script: str | os.PathLike, args: Sequence[str]) -> str:
    """The console line an owner would type: '& <script> <args>' with parameter tokens kept and values quoted."""
    parts = ['&', _ps_quote(str(script))]
    for arg in args:
        text = str(arg)
        if re.fullmatch(r'-[A-Za-z_][A-Za-z0-9_]*:?', text):
            parts.append(text)
            continue
        match = re.fullmatch(r'(-[A-Za-z_][A-Za-z0-9_]*):(.+)', text, re.S)
        if match:
            parts.append(match.group(1) + ':' + _ps_value(match.group(2)))
        else:
            parts.append(_ps_value(text))
    return ' '.join(parts)


def _ps_value(text: str) -> str:
    if text in ('$true', '$false', '$null') or re.fullmatch(r'-?[0-9]{1,9}', text):
        return text
    return _ps_quote(text)


def _ps_quote(text: str) -> str:
    out = []
    for char in text:
        out.append(char)
        if char in "'\u2018\u2019\u201a\u201b":
            out.append(char)
    return "'" + ''.join(out) + "'"


def _normalize_stub(stub: dict | None) -> dict:
    merged = default_stub() if stub is None else copy.deepcopy(stub)
    unknown = set(merged) - _STUB_KEYS
    if unknown:
        raise ValueError(f'unknown stub keys: {sorted(unknown)}')
    base = default_stub()
    for key in _STUB_KEYS:
        merged.setdefault(key, base[key])
    host = dict(base['host'])
    host.update(merged['host'] or {})
    if set(host) - _HOST_KEYS:
        raise ValueError(f'unknown host keys: {sorted(set(host) - _HOST_KEYS)}')
    merged['host'] = host
    fs = {'read_roots': [], 'virtual_dirs': [], 'virtual_files': {}}
    fs.update(merged['fs'] or {})
    if set(fs) - _FS_KEYS:
        raise ValueError(f'unknown fs keys: {sorted(set(fs) - _FS_KEYS)}')
    merged['fs'] = fs
    processes = []
    for entry in merged['processes'] or []:
        if set(entry) - _PROCESS_KEYS:
            raise ValueError(f'unknown process keys: {sorted(set(entry) - _PROCESS_KEYS)}')
        path = entry.get('path')
        processes.append({'pid': int(entry['pid']), 'parent_pid': int(entry.get('parent_pid', 0)),
                          'name': entry.get('name') or (Path(path).name if path else 'unknown.exe'), 'path': path,
                          'command_line': entry.get('command_line'), 'owner': entry.get('owner'),
                          'created_utc': entry.get('created_utc', '2026-10-11T15:00:00Z'),
                          'session_id': int(entry.get('session_id', 1)),
                          'visible_unelevated': bool(entry.get('visible_unelevated', False))})
    merged['processes'] = processes
    merged['listeners'] = [{'port': int(e['port']), 'pid': int(e.get('pid', 0)), 'address': e.get('address', '127.0.0.1')}
                           for e in merged['listeners'] or []]
    natives = {}
    for key, rules in (merged['natives'] or {}).items():
        rules = [rules] if isinstance(rules, dict) else list(rules)
        natives[str(key).lower()] = [{'match': r.get('match', ''), 'exit': int(r.get('exit', 0)),
                                      'stdout': r.get('stdout', ''), 'stderr': r.get('stderr', '')} for r in rules]
    merged['natives'] = natives
    merged['tasks'] = dict(merged['tasks'] or {})
    merged['tasks'].setdefault('*', 'denied')
    merged['http'] = dict(merged['http'] or {})
    merged['sleep_budget'] = int(merged['sleep_budget'])
    merged['pure_extra'] = [str(x) for x in merged['pure_extra'] or []]
    return merged


def run_toplevel(script: str | os.PathLike, args: Sequence[str] = (), *, stub: dict | None = None,
                 invocation: str = 'file', timeout: float = DEFAULT_TIMEOUT, keep_temp: bool = False) -> SmokeResult:
    """Run one deployment script top level in plan mode with the host stubbed; see the module docstring."""
    args = tuple(str(a) for a in args)
    offending = apply_argument(args)
    if offending is not None:
        raise SmokeRefused(f'{offending!r} would bind -Apply; ps_toplevel_smoke only runs plan mode')
    if invocation not in ('file', 'command'):
        raise ValueError("invocation must be 'file' or 'command'")
    target = Path(script).resolve()
    if target.suffix.lower() != '.ps1' or not target.is_file():
        raise SmokeRefused(f'not a .ps1 file: {target}')
    if not POWERSHELL.is_file():
        raise SmokeRefused(f'Windows PowerShell 5.1 not found at {POWERSHELL}')
    normalized = _normalize_stub(stub)
    keep = keep_temp or os.environ.get('PS_TOPLEVEL_SMOKE_KEEP') == '1'
    temp = Path(tempfile.mkdtemp(prefix='ps-toplevel-smoke-'))
    try:
        vdir = temp / 'vfiles'
        vdir.mkdir()
        mapping = {}
        for index, (virtual, content) in enumerate(sorted(normalized['fs']['virtual_files'].items())):
            real = vdir / f'{index:03d}-{hashlib.sha256(virtual.lower().encode()).hexdigest()[:12]}.dat'
            real.write_bytes(content.encode('utf-8') if isinstance(content, str) else bytes(content))
            mapping[virtual] = str(real)
        fs = normalized['fs']
        roots = list(fs['read_roots']) + [str(target.parent)]
        stub_for_ps = dict(normalized)
        stub_for_ps['fs'] = {'read_roots': roots, 'virtual_dirs': list(fs['virtual_dirs']), 'virtual_file_map': mapping}
        bootstrap, shim, spec_path, result_path = temp / 'bootstrap.ps1', temp / 'shim.cs', temp / 'spec.json', temp / 'result.json'
        bootstrap.write_text(_BOOTSTRAP_PS1, encoding='ascii')
        shim.write_text(_SHIM_CS, encoding='ascii')
        spec = {'schema': 'ps-toplevel-smoke-spec/1', 'target': str(target), 'args': list(args), 'invocation': invocation,
                'command_text': render_command_text(target, args), 'result_path': str(result_path),
                'shim_source_path': str(shim), 'pure': sorted(set(PURE_CMDLETS) | set(normalized['pure_extra'])),
                'stub': stub_for_ps}
        spec_path.write_text(json.dumps(spec, indent=1), encoding='utf-8')
        command = ("$ProgressPreference='SilentlyContinue'; . " + _ps_quote(str(bootstrap)) + ' ' + _ps_quote(str(spec_path))
                   + '; exit $global:PsSmokeExit')
        argv = [str(POWERSHELL), '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command]
        env = dict(os.environ)
        env['PSModulePath'] = str(PSHOME / 'Modules')
        started = time.monotonic()
        try:
            run = subprocess.run(argv, cwd=str(target.parent), env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                 timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise SmokeHarnessError(f'{target.name} did not finish within {timeout} s (the child was terminated)') from exc
        duration = time.monotonic() - started
        stdout = run.stdout.decode('utf-8', errors='replace')
        stderr = run.stderr.decode('utf-8', errors='replace')
        if not result_path.is_file():
            raise SmokeHarnessError(f'no result was written (exit {run.returncode})\nstdout: {stdout[-2000:]}\nstderr: {stderr[-3000:]}')
        data = json.loads(result_path.read_text(encoding='utf-8-sig'))
        if data.get('schema') != RESULT_SCHEMA:
            raise SmokeHarnessError(f'unexpected result schema {data.get("schema")!r}')
        return SmokeResult(
            script=str(target), args=args, invocation=invocation, exit_code=data.get('exit_code'),
            process_exit_code=run.returncode, stdout=stdout, stderr=stderr,
            error=ErrorInfo.from_json(data.get('terminating_error')),
            errors=tuple(e for e in (ErrorInfo.from_json(x) for x in data.get('non_terminating_errors') or []) if e),
            trace=tuple(data.get('trace') or []), self_test=dict(data.get('self_test') or {}), refused=data.get('refused'),
            bootstrap_error=data.get('bootstrap_error'), guard_intact=data.get('guard_intact'), duration_s=duration,
            temp_dir=str(temp) if keep else None)
    finally:
        if not keep:
            shutil.rmtree(temp, ignore_errors=True)


def plan_mode_outcome(result: SmokeResult, *, plan_schema: str | None = None) -> str:
    """'plan' or 'refusal' for a run that behaved like a plan-mode run must; raises a PlanModeAssertion otherwise."""
    result.raise_for_harness()
    if result.denied:
        raise HostAccessDenied('the target reached host commands that are not stubbed (blocked, not executed):\n'
                               + result.describe())
    if result.error is not None and result.error.is_binding:
        cls = PsVariableValidationError if result.error.variable else PsBindingError
        raise cls(result.describe())
    for error in result.errors:
        if error.is_binding:
            cls = PsVariableValidationError if error.variable else PsBindingError
            raise cls('non-terminating binding error: ' + error.describe() + '\n' + result.describe())
    if result.exit_code == 0 and result.error is None:
        plan = result.plan
        if not isinstance(plan, dict) or plan.get('mode') != 'READ_ONLY_PLAN':
            raise PlanModeError('exit 0 without a READ_ONLY_PLAN JSON document\n' + result.describe()
                                + '\nstdout: ' + result.stdout[:1500])
        if plan_schema is not None and plan.get('schema') != plan_schema:
            raise PlanModeError(f'plan schema {plan.get("schema")!r} != {plan_schema!r}\n' + result.describe())
        return 'plan'
    if result.error is None:
        raise PlanModeError(f'exit {result.exit_code} without a terminating error\n' + result.describe())
    if not result.error.is_clean_refusal:
        raise PlanModeError('not a clean refusal (engine error):\n' + result.describe())
    if result.exit_code != 1:
        raise PlanModeError(f'a refusal must exit 1, not {result.exit_code}\n' + result.describe())
    return 'refusal'


def assert_plan_or_clean_refusal(result: SmokeResult, *, plan_schema: str | None = None) -> str:
    """Alias of plan_mode_outcome() for readability in tests."""
    return plan_mode_outcome(result, plan_schema=plan_schema)


_SHIM_CS = r'''
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Security.Principal;
using System.Text;

namespace PsToplevelSmoke
{
    public sealed class TraceEntry
    {
        public int seq; public string kind; public string command; public string detail;
    }

    public static class Policy
    {
        public static readonly List<TraceEntry> Trace = new List<TraceEntry>();
        public static readonly Dictionary<string, string> Files = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public static string[] Roots = new string[0];
        public static bool Elevated;
        public const int Limit = 20000;

        public static void Configure(string[] roots, bool elevated) { Roots = roots ?? new string[0]; Elevated = elevated; }
        public static void MapFile(string virtualPath, string realPath) { Files[Key(virtualPath)] = realPath; }
        public static void Truncate(int count) { if (count < Trace.Count) Trace.RemoveRange(count, Trace.Count - count); }

        public static void Add(string kind, string command, string detail)
        {
            if (Trace.Count > Limit) return;
            if (Trace.Count == Limit) { Trace.Add(new TraceEntry { seq = Limit + 1, kind = "truncated", command = "", detail = "trace limit reached" }); return; }
            if (detail != null && detail.Length > 4000) detail = detail.Substring(0, 4000) + "...";
            Trace.Add(new TraceEntry { seq = Trace.Count + 1, kind = kind, command = command, detail = detail });
        }

        public static string Key(string path)
        {
            string full = Path.GetFullPath(path);
            if (full.Length > 3) full = full.TrimEnd('\\');
            return full;
        }

        public static bool Under(string full, string root)
        {
            if (string.Equals(full, root, StringComparison.OrdinalIgnoreCase)) return true;
            string prefix = root.EndsWith("\\") ? root : root + "\\";
            return full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
        }

        public static bool IsRealRoot(string key)
        {
            foreach (string r in Roots) if (Under(key, r)) return true;
            return false;
        }

        public static string Read(string member, string path)
        {
            if (path == null) throw new ArgumentNullException("path");
            string key = Key(path);
            string mapped;
            if (Files.TryGetValue(key, out mapped)) { Add("fs-virtual", "[IO.File]::" + member, key + " [vfile]"); return mapped; }
            if (IsRealRoot(key)) { Add("fs-real", "[IO.File]::" + member, key); return key; }
            Add("fs-virtual", "[IO.File]::" + member, key + " [absent]");
            throw new FileNotFoundException("Could not find file '" + key + "'.", key);
        }

        public static Exception Deny(string member, string path)
        {
            Add("denied", "[IO.File]::" + member, path);
            return new InvalidOperationException("SmokeDenied: [IO.File]::" + member + " (" + path + ") would change the host; nothing was written.");
        }
    }

    public sealed class ComCollection : IEnumerable
    {
        private readonly object[] items;
        public ComCollection(object[] items) { this.items = items ?? new object[0]; }
        public int Count { get { return items.Length; } }
        public object Item(int index)
        {
            if (index < 1 || index > items.Length) throw new ArgumentOutOfRangeException("index");
            return items[index - 1];
        }
        public IEnumerator GetEnumerator() { return items.GetEnumerator(); }
    }

    public static class ShimFile
    {
        private static bool Writes(FileMode mode, FileAccess access) { return mode != FileMode.Open || (access & FileAccess.Write) != 0; }
        public static FileStream Open(string path, FileMode mode) { throw Policy.Deny("Open", path); }
        public static FileStream Open(string path, FileMode mode, FileAccess access) { return Open(path, mode, access, FileShare.None); }
        public static FileStream Open(string path, FileMode mode, FileAccess access, FileShare share)
        {
            if (Writes(mode, access)) throw Policy.Deny("Open", path);
            return File.Open(Policy.Read("Open", path), mode, access, share);
        }
        public static FileStream OpenRead(string path) { return File.OpenRead(Policy.Read("OpenRead", path)); }
        public static StreamReader OpenText(string path) { return File.OpenText(Policy.Read("OpenText", path)); }
        public static byte[] ReadAllBytes(string path) { return File.ReadAllBytes(Policy.Read("ReadAllBytes", path)); }
        public static string ReadAllText(string path) { return File.ReadAllText(Policy.Read("ReadAllText", path)); }
        public static string ReadAllText(string path, Encoding encoding) { return File.ReadAllText(Policy.Read("ReadAllText", path), encoding); }
        public static string[] ReadAllLines(string path) { return File.ReadAllLines(Policy.Read("ReadAllLines", path)); }
        public static string[] ReadAllLines(string path, Encoding encoding) { return File.ReadAllLines(Policy.Read("ReadAllLines", path), encoding); }
        public static IEnumerable<string> ReadLines(string path) { return File.ReadLines(Policy.Read("ReadLines", path)); }
        public static IEnumerable<string> ReadLines(string path, Encoding encoding) { return File.ReadLines(Policy.Read("ReadLines", path), encoding); }
        public static FileAttributes GetAttributes(string path) { return File.GetAttributes(Policy.Read("GetAttributes", path)); }
        public static DateTime GetLastWriteTimeUtc(string path) { return File.GetLastWriteTimeUtc(Policy.Read("GetLastWriteTimeUtc", path)); }
        public static DateTime GetLastWriteTime(string path) { return File.GetLastWriteTime(Policy.Read("GetLastWriteTime", path)); }
        public static bool Exists(string path)
        {
            if (path == null) return false;
            string key;
            try { key = Policy.Key(path); } catch (Exception) { return false; }
            if (Policy.Files.ContainsKey(key)) { Policy.Add("fs-virtual", "[IO.File]::Exists", key + " [vfile]"); return true; }
            if (Policy.IsRealRoot(key)) { Policy.Add("fs-real", "[IO.File]::Exists", key); return File.Exists(key); }
            Policy.Add("fs-virtual", "[IO.File]::Exists", key + " [absent]");
            return false;
        }
        public static void WriteAllText(string path, string contents) { throw Policy.Deny("WriteAllText", path); }
        public static void WriteAllText(string path, string contents, Encoding encoding) { throw Policy.Deny("WriteAllText", path); }
        public static void WriteAllBytes(string path, byte[] bytes) { throw Policy.Deny("WriteAllBytes", path); }
        public static void WriteAllLines(string path, string[] contents) { throw Policy.Deny("WriteAllLines", path); }
        public static void WriteAllLines(string path, string[] contents, Encoding encoding) { throw Policy.Deny("WriteAllLines", path); }
        public static void WriteAllLines(string path, IEnumerable<string> contents) { throw Policy.Deny("WriteAllLines", path); }
        public static void WriteAllLines(string path, IEnumerable<string> contents, Encoding encoding) { throw Policy.Deny("WriteAllLines", path); }
        public static void AppendAllText(string path, string contents) { throw Policy.Deny("AppendAllText", path); }
        public static void AppendAllText(string path, string contents, Encoding encoding) { throw Policy.Deny("AppendAllText", path); }
        public static void AppendAllLines(string path, IEnumerable<string> contents) { throw Policy.Deny("AppendAllLines", path); }
        public static void AppendAllLines(string path, IEnumerable<string> contents, Encoding encoding) { throw Policy.Deny("AppendAllLines", path); }
        public static StreamWriter AppendText(string path) { throw Policy.Deny("AppendText", path); }
        public static StreamWriter CreateText(string path) { throw Policy.Deny("CreateText", path); }
        public static FileStream Create(string path) { throw Policy.Deny("Create", path); }
        public static FileStream Create(string path, int bufferSize) { throw Policy.Deny("Create", path); }
        public static FileStream Create(string path, int bufferSize, FileOptions options) { throw Policy.Deny("Create", path); }
        public static FileStream OpenWrite(string path) { throw Policy.Deny("OpenWrite", path); }
        public static void Delete(string path) { throw Policy.Deny("Delete", path); }
        public static void Copy(string source, string destination) { throw Policy.Deny("Copy", destination); }
        public static void Copy(string source, string destination, bool overwrite) { throw Policy.Deny("Copy", destination); }
        public static void Move(string source, string destination) { throw Policy.Deny("Move", source + " -> " + destination); }
        public static void Replace(string source, string destination, string backup) { throw Policy.Deny("Replace", destination); }
        public static void Replace(string source, string destination, string backup, bool ignoreMetadataErrors) { throw Policy.Deny("Replace", destination); }
        public static void SetAttributes(string path, FileAttributes attributes) { throw Policy.Deny("SetAttributes", path); }
        public static void SetLastWriteTime(string path, DateTime value) { throw Policy.Deny("SetLastWriteTime", path); }
        public static void SetLastWriteTimeUtc(string path, DateTime value) { throw Policy.Deny("SetLastWriteTimeUtc", path); }
        public static void SetCreationTime(string path, DateTime value) { throw Policy.Deny("SetCreationTime", path); }
        public static void SetCreationTimeUtc(string path, DateTime value) { throw Policy.Deny("SetCreationTimeUtc", path); }
        public static void SetLastAccessTime(string path, DateTime value) { throw Policy.Deny("SetLastAccessTime", path); }
        public static void SetLastAccessTimeUtc(string path, DateTime value) { throw Policy.Deny("SetLastAccessTimeUtc", path); }
        public static void Encrypt(string path) { throw Policy.Deny("Encrypt", path); }
        public static void Decrypt(string path) { throw Policy.Deny("Decrypt", path); }
    }

    public sealed class ShimPrincipal
    {
        private readonly WindowsPrincipal real;
        public ShimPrincipal(WindowsIdentity ntIdentity) { real = new WindowsPrincipal(ntIdentity); }
        public IIdentity Identity { get { return real.Identity; } }
        private static bool Answer(string role)
        {
            Policy.Add("stub", "[Security.Principal.WindowsPrincipal]::IsInRole", role + " -> " + (Policy.Elevated ? "True" : "False"));
            return Policy.Elevated;
        }
        public bool IsInRole(WindowsBuiltInRole role)
        {
            if (role == WindowsBuiltInRole.Administrator) return Answer("Administrator");
            return real.IsInRole(role);
        }
        public bool IsInRole(int rid)
        {
            if (rid == 0x220) return Answer("Administrator");
            return real.IsInRole(rid);
        }
        public bool IsInRole(SecurityIdentifier sid)
        {
            if (sid != null && sid.IsWellKnown(WellKnownSidType.BuiltinAdministratorsSid)) return Answer("Administrator");
            return real.IsInRole(sid);
        }
        public bool IsInRole(string role)
        {
            if (role != null && (role.Equals("BUILTIN\\Administrators", StringComparison.OrdinalIgnoreCase) || role.Equals("Administrators", StringComparison.OrdinalIgnoreCase))) return Answer("Administrator");
            return real.IsInRole(role);
        }
    }
}
'''

_BOOTSTRAP_PS1 = r'''# ps_toplevel_smoke bootstrap (ps-toplevel-smoke-bootstrap/1). Written by ps_toplevel_smoke.py into a temporary
# directory and dot-sourced at global scope; it runs the target in plan mode only and never with -Apply.
param([string]$PsSmokeSpecPath)
$global:PsSmokeExit = 90
$global:PsSmokeClock = [System.Diagnostics.Stopwatch]::StartNew()
$global:PsSmokeReady = $false
$global:PsSmokeResultPath = $null
$global:PsSmokeResult = [ordered]@{
    schema = 'ps-toplevel-smoke-result/1'; bootstrap_ok = $false; refused = $null; bootstrap_error = $null
    self_test = [ordered]@{}; exit_code = $null; exit_source = $null; terminating_error = $null
    non_terminating_errors = @(); output_count = 0; guard_intact = $null; duration_ms = 0; trace = @()
}

function global:Write-PsSmokeResult {
    $r = $global:PsSmokeResult
    $r.duration_ms = [int]$global:PsSmokeClock.ElapsedMilliseconds
    $entries = [System.Collections.Generic.List[object]]::new()
    try { foreach ($t in [PsToplevelSmoke.Policy]::Trace) { $entries.Add([ordered]@{ seq = $t.seq; kind = $t.kind; command = $t.command; detail = $t.detail }) } } catch { }
    $r.trace = $entries.ToArray()
    $json = ConvertTo-Json -InputObject $r -Depth 6 -Compress
    if ($global:PsSmokeResultPath) { [System.IO.File]::WriteAllText($global:PsSmokeResultPath, $json, [System.Text.UTF8Encoding]::new($false)) }
}

function global:ConvertTo-PsSmokeErrorInfo {
    # $Item is an ErrorRecord from the error stream (shown as written) or the exception PowerShell.Invoke() threw
    # (MethodInvocationException around the record-carrying exception the console host would have shown).
    param($Item)
    $console = $null
    $ex = $Item
    if ($Item -is [System.Management.Automation.ErrorRecord]) { $console = $Item; $ex = $Item.Exception }
    while ($ex -is [System.Management.Automation.MethodInvocationException] -and $null -ne $ex.InnerException) { $ex = $ex.InnerException }
    if ($null -eq $console -and $ex -is [System.Management.Automation.IContainsErrorRecord]) { $console = $ex.ErrorRecord }
    $inner = $ex
    while (($inner -is [System.Management.Automation.CmdletInvocationException] -or $inner -is [System.Management.Automation.MethodInvocationException] -or $inner -is [System.Management.Automation.CmdletProviderInvocationException]) -and $null -ne $inner.InnerException) { $inner = $inner.InnerException }
    $record = $console
    if ($inner -is [System.Management.Automation.IContainsErrorRecord]) { $record = $inner.ErrorRecord }
    if ($null -eq $record) { $record = $console }
    $chain = [System.Collections.Generic.List[string]]::new()
    $walk = $ex
    while ($null -ne $walk -and $chain.Count -lt 12) { $chain.Add($walk.GetType().FullName); $walk = $walk.InnerException }
    $info = [ordered]@{ fqid = ''; inner_fqid = ''; category = ''; exception_type = $inner.GetType().FullName; chain = $chain.ToArray()
        message = [string]$inner.Message; script_name = ''; line = 0; line_text = '' }
    if ($null -ne $console) { $info.fqid = [string]$console.FullyQualifiedErrorId }
    if ($null -ne $record) {
        $info.inner_fqid = [string]$record.FullyQualifiedErrorId
        if (-not $info.fqid) { $info.fqid = $info.inner_fqid }
        $info.category = [string]$record.CategoryInfo.Category
        if ($null -ne $record.InvocationInfo) {
            $info.script_name = [string]$record.InvocationInfo.ScriptName
            $info.line = [int]$record.InvocationInfo.ScriptLineNumber
            $text = [string]$record.InvocationInfo.Line
            if ($text.Length -gt 400) { $text = $text.Substring(0, 400) }
            $info.line_text = $text.Trim()
        }
    }
    $info
}

function global:ConvertTo-PsSmokeKey {
    param([string]$Path)
    Set-StrictMode -Off
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full.Length -gt 3) { $full = $full.TrimEnd('\') }
    $full
}

function global:Add-PsSmokeDirChain {
    param([string]$Key, [bool]$IncludeSelf)
    Set-StrictMode -Off
    $p = $Key
    if (-not $IncludeSelf) { $p = [System.IO.Path]::GetDirectoryName($Key) }
    while ($p) {
        $k = $p
        if ($k.Length -gt 3) { $k = $k.TrimEnd('\') }
        [void]$global:PsSmoke.VirtualDirs.Add($k)
        $parent = [System.IO.Path]::GetDirectoryName($p)
        if (-not $parent -or $parent -eq $p) { break }
        $p = $parent
    }
}

function global:Invoke-PsSmokeDeny {
    param([string]$Command, [string]$Why)
    Set-StrictMode -Off
    [PsToplevelSmoke.Policy]::Add('denied', $Command, $Why)
    throw [System.InvalidOperationException]::new('SmokeDenied: ' + $Command + ' (' + $Why + '); nothing was executed.')
}

function global:Write-PsSmokeError {
    param($Cmdlet, [System.Exception]$Exception, [string]$ErrorId, [System.Management.Automation.ErrorCategory]$Category, $TargetObject)
    Set-StrictMode -Off
    $Cmdlet.WriteError([System.Management.Automation.ErrorRecord]::new($Exception, $ErrorId, $Category, $TargetObject))
}

function global:Write-PsSmokeNotFound {
    param($Cmdlet, [string]$Path)
    Set-StrictMode -Off
    Write-PsSmokeError $Cmdlet ([System.Management.Automation.ItemNotFoundException]::new("Cannot find path '" + $Path + "' because it does not exist.")) 'PathNotFound' ([System.Management.Automation.ErrorCategory]::ObjectNotFound) $Path
}

function global:Copy-PsSmokeBound {
    param([hashtable]$Bound, [string]$Path, [bool]$Literal)
    Set-StrictMode -Off
    $copy = @{}
    foreach ($k in $Bound.Keys) { if ($k -ne 'Path' -and $k -ne 'LiteralPath') { $copy[$k] = $Bound[$k] } }
    if ($null -ne $Path) { if ($Literal) { $copy['LiteralPath'] = $Path } else { $copy['Path'] = $Path } }
    $copy
}

function global:Resolve-PsSmokePath {
    param([string]$Path, [bool]$Literal)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $p = $Path -replace '^(?i)(Microsoft\.PowerShell\.Core\\)?FileSystem::', ''
    if ($p -match '^(?i)((Microsoft\.PowerShell\.Core\\)?(Registry|Certificate|WSMan)::|HKLM:|HKCU:|HKCR:|HKU:|HKCC:|Cert:|WSMan:)') { return @{ Kind = 'denied'; Full = $p; Why = 'non-file-system provider path' } }
    if ($p -match '^(?i)(Env|Variable|Function|Alias):') { return @{ Kind = 'session'; Full = $p } }
    if ($p -match '^[A-Za-z][A-Za-z0-9_]+:') { return @{ Kind = 'denied'; Full = $p; Why = 'unknown provider path' } }
    $base = $ExecutionContext.SessionState.Path.CurrentFileSystemLocation.ProviderPath
    $wild = (-not $Literal) -and ($p.IndexOfAny([char[]]@('*', '?', '[')) -ge 0)
    if ($wild) {
        $full = $p
        if (-not [System.IO.Path]::IsPathRooted($p)) { $full = $base.TrimEnd('\') + '\' + $p }
        foreach ($r in $s.Roots) { if ($full.StartsWith($r + '\', [StringComparison]::OrdinalIgnoreCase)) { return @{ Kind = 'real'; Full = $full } } }
        return @{ Kind = 'vwild'; Full = $full }
    }
    $key = ConvertTo-PsSmokeKey ([System.IO.Path]::Combine($base, $p))
    if ($s.VirtualFiles.ContainsKey($key)) { return @{ Kind = 'vfile'; Full = $key; Mapped = $s.VirtualFiles[$key] } }
    if ([PsToplevelSmoke.Policy]::IsRealRoot($key)) { return @{ Kind = 'real'; Full = $key } }
    if ($s.VirtualDirs.Contains($key)) { return @{ Kind = 'vdir'; Full = $key } }
    @{ Kind = 'absent'; Full = $key }
}

function global:New-PsSmokeItem {
    param([string]$Full, [bool]$Directory)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $parentPath = [System.IO.Path]::GetDirectoryName($Full)
    $parent = $null
    if ($parentPath) { $parent = New-PsSmokeItem (ConvertTo-PsSmokeKey $parentPath) $true }
    $name = [System.IO.Path]::GetFileName($Full)
    if (-not $name) { $name = $Full }
    $length = [long]0
    if (-not $Directory -and $s.VirtualFiles.ContainsKey($Full)) { $length = ([System.IO.FileInfo]::new($s.VirtualFiles[$Full])).Length }
    $stamp = [datetime]::new(2026, 10, 11, 0, 0, 0, [System.DateTimeKind]::Utc)
    $attributes = [System.IO.FileAttributes]::Archive
    $mode = '-a----'
    if ($Directory) { $attributes = [System.IO.FileAttributes]::Directory; $mode = 'd-----' }
    $parentPsPath = ''
    if ($parentPath) { $parentPsPath = 'Microsoft.PowerShell.Core\FileSystem::' + $parentPath }
    $item = [pscustomobject][ordered]@{
        PSPath = 'Microsoft.PowerShell.Core\FileSystem::' + $Full; PSParentPath = $parentPsPath; PSChildName = $name
        PSProvider = 'Microsoft.PowerShell.Core\FileSystem'; PSIsContainer = $Directory; Name = $name; FullName = $Full
        BaseName = [System.IO.Path]::GetFileNameWithoutExtension($Full); Extension = [System.IO.Path]::GetExtension($Full)
        Exists = $true; Length = $length; Attributes = $attributes; Mode = $mode; IsReadOnly = $false
        CreationTime = $stamp.ToLocalTime(); CreationTimeUtc = $stamp; LastWriteTime = $stamp.ToLocalTime(); LastWriteTimeUtc = $stamp
        LastAccessTime = $stamp.ToLocalTime(); LastAccessTimeUtc = $stamp; Parent = $parent; Directory = $parent
        DirectoryName = $parentPath; LinkType = $null; Target = $null; PsSmokeVirtual = $true
    }
    if ($Directory) { $item.PSObject.TypeNames.Insert(0, 'PsSmoke.VirtualDirectoryInfo') } else { $item.PSObject.TypeNames.Insert(0, 'PsSmoke.VirtualFileInfo') }
    $item
}

function global:Get-PsSmokeChildren {
    param([string]$Dir, [bool]$Recurse)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $prefix = $Dir
    if (-not $prefix.EndsWith('\')) { $prefix = $prefix + '\' }
    $found = [System.Collections.Generic.SortedDictionary[string, bool]]::new([StringComparer]::OrdinalIgnoreCase)
    $candidates = @()
    foreach ($d in $s.VirtualDirs) { $candidates += , @($d, $true) }
    foreach ($r in $s.Roots) { $candidates += , @($r, $true) }
    foreach ($f in $s.VirtualFiles.Keys) { $candidates += , @($f, $false) }
    foreach ($c in $candidates) {
        $path = [string]$c[0]
        if ($path.Length -le $prefix.Length -or -not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { continue }
        if (-not $Recurse -and $path.IndexOf('\', $prefix.Length) -ge 0) { continue }
        if (-not $found.ContainsKey($path)) { $found[$path] = [bool]$c[1] }
    }
    foreach ($k in $found.Keys) { @{ Full = $k; Directory = $found[$k] } }
}

function global:Invoke-PsSmokeFs {
    param([string]$Name, $Cmdlet, [hashtable]$Bound)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $literal = $Bound.ContainsKey('LiteralPath')
    $paths = @()
    if ($literal) { $paths = @($Bound['LiteralPath']) } elseif ($Bound.ContainsKey('Path')) { $paths = @($Bound['Path']) }
    if ($paths.Count -eq 0) {
        if ($Name -eq 'Get-FileHash' -and $Bound.ContainsKey('InputStream')) { [PsToplevelSmoke.Policy]::Add('stub', $Name, 'InputStream (pure)'); return & $s.Real[$Name] @Bound }
        if ($Name -eq 'Get-ChildItem' -or $Name -eq 'Get-Acl') { $paths = @('.') }
        else { Invoke-PsSmokeDeny $Name 'parameter set is not modeled (no -Path/-LiteralPath)' }
    }
    foreach ($p in $paths) {
        $r = Resolve-PsSmokePath ([string]$p) $literal
        if ($r.Kind -eq 'denied') { Invoke-PsSmokeDeny $Name ($r.Why + ': ' + $p) }
        if ($r.Kind -eq 'session' -or $r.Kind -eq 'real') {
            [PsToplevelSmoke.Policy]::Add($(if ($r.Kind -eq 'real') { 'fs-real' } else { 'stub' }), $Name, [string]$r.Full)
            $one = Copy-PsSmokeBound $Bound ([string]$p) $literal
            & $s.Real[$Name] @one
            continue
        }
        Invoke-PsSmokeFsVirtual $Name $Cmdlet $Bound $r ([string]$p)
    }
}

function global:Invoke-PsSmokeFsVirtual {
    param([string]$Name, $Cmdlet, [hashtable]$Bound, $R, [string]$Original)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $kind = $R.Kind
    $full = [string]$R.Full
    $existing = @()
    if ($kind -eq 'vwild') {
        foreach ($d in $s.VirtualDirs) { if ($d -like $full) { $existing += , @{ Full = $d; Directory = $true } } }
        foreach ($f in $s.VirtualFiles.Keys) { if ($f -like $full) { $existing += , @{ Full = $f; Directory = $false } } }
    } elseif ($kind -eq 'vfile') { $existing = @(@{ Full = $full; Directory = $false }) }
    elseif ($kind -eq 'vdir') { $existing = @(@{ Full = $full; Directory = $true }) }
    [PsToplevelSmoke.Policy]::Add('fs-virtual', $Name, $full + ' [' + $kind + ']')
    switch ($Name) {
        'Test-Path' {
            if ($Bound.ContainsKey('IsValid')) { return & $s.Real[$Name] -Path $Original -IsValid }
            $type = 'Any'
            if ($Bound.ContainsKey('PathType')) { $type = [string]$Bound['PathType'] }
            foreach ($e in $existing) {
                if ($type -eq 'Leaf' -and $e.Directory) { continue }
                if ($type -eq 'Container' -and -not $e.Directory) { continue }
                return $true
            }
            return $false
        }
        'Get-Item' {
            if ($existing.Count -eq 0) { Write-PsSmokeNotFound $Cmdlet $Original; return }
            foreach ($e in $existing) { New-PsSmokeItem $e.Full $e.Directory }
        }
        'Get-ChildItem' {
            if ($existing.Count -eq 0) { Write-PsSmokeNotFound $Cmdlet $Original; return }
            $recurse = $Bound.ContainsKey('Recurse') -and [bool]$Bound['Recurse']
            $items = @()
            foreach ($e in $existing) { if ($e.Directory) { $items += @(Get-PsSmokeChildren $e.Full $recurse) } else { $items += , $e } }
            foreach ($c in $items) {
                if ($Bound.ContainsKey('Directory') -and [bool]$Bound['Directory'] -and -not $c.Directory) { continue }
                if ($Bound.ContainsKey('File') -and [bool]$Bound['File'] -and $c.Directory) { continue }
                $leaf = [System.IO.Path]::GetFileName($c.Full)
                if ($Bound.ContainsKey('Filter') -and $Bound['Filter'] -and -not ($leaf -like [string]$Bound['Filter'])) { continue }
                if ($Bound.ContainsKey('Include') -and $Bound['Include']) { $hit = $false; foreach ($pattern in @($Bound['Include'])) { if ($leaf -like [string]$pattern) { $hit = $true } }; if (-not $hit) { continue } }
                if ($Bound.ContainsKey('Exclude') -and $Bound['Exclude']) { $hit = $false; foreach ($pattern in @($Bound['Exclude'])) { if ($leaf -like [string]$pattern) { $hit = $true } }; if ($hit) { continue } }
                if ($Bound.ContainsKey('Name') -and [bool]$Bound['Name']) { $leaf } else { New-PsSmokeItem $c.Full $c.Directory }
            }
        }
        'Get-Content' {
            if ($kind -ne 'vfile') {
                if ($kind -eq 'vdir') { Write-PsSmokeError $Cmdlet ([System.UnauthorizedAccessException]::new("Access to the path '" + $full + "' is denied.")) 'GetContentReaderUnauthorizedAccessError' ([System.Management.Automation.ErrorCategory]::PermissionDenied) $full }
                else { Write-PsSmokeNotFound $Cmdlet $Original }
                return
            }
            $one = Copy-PsSmokeBound $Bound ([string]$R.Mapped) $true
            & $s.Real[$Name] @one
        }
        'Get-FileHash' {
            if ($kind -ne 'vfile') { Write-PsSmokeNotFound $Cmdlet $Original; return }
            $one = Copy-PsSmokeBound $Bound ([string]$R.Mapped) $true
            $h = & $s.Real[$Name] @one
            [pscustomobject]@{ Algorithm = $h.Algorithm; Hash = $h.Hash; Path = $full }
        }
        'Get-Acl' {
            if ($existing.Count -eq 0) { Write-PsSmokeNotFound $Cmdlet $Original; return }
            Write-PsSmokeError $Cmdlet ([System.UnauthorizedAccessException]::new('SmokeVirtualAcl: the ACL of a virtual path cannot be read: ' + $full)) 'SmokeVirtualAcl' ([System.Management.Automation.ErrorCategory]::PermissionDenied) $full
        }
        'Resolve-Path' {
            if ($existing.Count -eq 0) { Write-PsSmokeNotFound $Cmdlet $Original; return }
            foreach ($e in $existing) { [pscustomobject]@{ Path = $e.Full; ProviderPath = $e.Full; Provider = 'Microsoft.PowerShell.Core\FileSystem' } }
        }
        default { Invoke-PsSmokeDeny $Name 'virtual path handling is not modeled' }
    }
}

function global:Test-PsSmokeVisible {
    param($P)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    if ($s.Elevated -or [bool]$P.visible_unelevated) { return $true }
    return ($null -ne $P.owner -and [string]::Equals([string]$P.owner, [string]$s.User, [StringComparison]::OrdinalIgnoreCase))
}

function global:ConvertTo-PsSmokeDate {
    param($Text)
    Set-StrictMode -Off
    [datetime]::Parse([string]$Text, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
}

function global:New-PsSmokeCimProcess {
    param($P)
    Set-StrictMode -Off
    $visible = Test-PsSmokeVisible $P
    $path = $null; $command = $null
    if ($visible) { $path = $P.path; $command = $P.command_line }
    $o = [pscustomobject][ordered]@{
        Caption = [string]$P.name; CommandLine = $command; CreationClassName = 'Win32_Process'; CreationDate = (ConvertTo-PsSmokeDate $P.created_utc).ToLocalTime()
        CSName = $env:COMPUTERNAME; Description = [string]$P.name; ExecutablePath = $path; Handle = [string]$P.pid; Name = [string]$P.name
        ParentProcessId = [uint32]$P.parent_pid; ProcessId = [uint32]$P.pid; SessionId = [uint32]$P.session_id; PSComputerName = $null
    }
    $o.PSObject.TypeNames.Insert(0, 'PsSmoke.Win32_Process')
    $o
}

function global:Select-PsSmokeProcesses {
    param([string]$Filter, [string]$Command)
    Set-StrictMode -Off
    $all = @($global:PsSmoke.Processes)
    if (-not $Filter -or -not $Filter.Trim()) { return $all }
    $m = [regex]::Match($Filter, '^\s*(ProcessId|ParentProcessId|Handle)\s*=\s*''?(\d+)''?\s*$', 'IgnoreCase')
    if ($m.Success) {
        $value = [int]$m.Groups[2].Value
        $field = 'pid'
        if ($m.Groups[1].Value -ieq 'ParentProcessId') { $field = 'parent_pid' }
        return @($all | Where-Object { [int]$_.$field -eq $value })
    }
    $m = [regex]::Match($Filter, '^\s*Name\s*=\s*''([^'']*)''\s*$', 'IgnoreCase')
    if ($m.Success) { $name = $m.Groups[1].Value; return @($all | Where-Object { [string]$_.name -ieq $name }) }
    Invoke-PsSmokeDeny $Command ('the CIM filter is not modeled: ' + $Filter)
}

function global:Invoke-PsSmokeCim {
    param([string]$Name, $Cmdlet, [hashtable]$Bound)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    foreach ($k in @('CimSession', 'ComputerName', 'ResourceUri', 'Credential', 'AsJob')) { if ($Bound.ContainsKey($k)) { Invoke-PsSmokeDeny $Name ('-' + $k + ' is not modeled') } }
    if ($Name -eq 'Invoke-CimMethod') {
        $method = [string]$Bound['MethodName']
        if (-not $Bound.ContainsKey('InputObject') -or $method -ne 'GetOwner') { Invoke-PsSmokeDeny $Name ('CIM method ' + $method + ' is not modeled') }
        $processId = [int]$Bound['InputObject'].ProcessId
        $p = @($s.Processes | Where-Object { [int]$_.pid -eq $processId }) | Select-Object -First 1
        [PsToplevelSmoke.Policy]::Add('stub', $Name, 'GetOwner pid ' + $processId)
        if ($null -eq $p) { Write-PsSmokeError $Cmdlet ([System.Management.Automation.ItemNotFoundException]::new('Not found ')) 'HRESULT 0x80041002' ([System.Management.Automation.ErrorCategory]::ObjectNotFound) $processId; return }
        if ($null -eq $p.owner -or -not (Test-PsSmokeVisible $p)) { return [pscustomobject]@{ Domain = $null; ReturnValue = [uint32]2; User = $null; PSComputerName = $null } }
        $parts = ([string]$p.owner).Split([char[]]@('\'), 2)
        $domain = $null; $user = $parts[0]
        if ($parts.Count -eq 2) { $domain = $parts[0]; $user = $parts[1] }
        return [pscustomobject]@{ Domain = $domain; ReturnValue = [uint32]0; User = $user; PSComputerName = $null }
    }
    $class = ''
    if ($Bound.ContainsKey('ClassName')) { $class = [string]$Bound['ClassName'] } elseif ($Bound.ContainsKey('Class')) { $class = [string]$Bound['Class'] }
    $filter = ''
    if ($Bound.ContainsKey('Filter')) { $filter = [string]$Bound['Filter'] }
    if ($Bound.ContainsKey('Query')) {
        $m = [regex]::Match([string]$Bound['Query'], '^\s*SELECT\s+\*\s+FROM\s+(\w+)(\s+WHERE\s+(.+))?\s*$', 'IgnoreCase')
        if (-not $m.Success) { Invoke-PsSmokeDeny $Name ('the CIM query is not modeled: ' + $Bound['Query']) }
        $class = $m.Groups[1].Value; $filter = $m.Groups[3].Value
    }
    if ($Bound.ContainsKey('InputObject')) { $class = 'Win32_Process'; $filter = 'ProcessId = ' + [int]$Bound['InputObject'].ProcessId }
    if ($Bound.ContainsKey('Namespace')) { $ns = ([string]$Bound['Namespace']).Replace('/', '\').Trim('\'); if ($ns -ne 'root\cimv2') { Invoke-PsSmokeDeny $Name ('CIM namespace ' + $ns + ' is not modeled') } }
    [PsToplevelSmoke.Policy]::Add('stub', $Name, ($class + ' ' + $filter).Trim())
    switch ($class) {
        'Win32_Process' {
            foreach ($p in @(Select-PsSmokeProcesses $filter $Name)) {
                $o = New-PsSmokeCimProcess $p
                if ($Name -eq 'Get-WmiObject') { $o | Add-Member -MemberType ScriptMethod -Name GetOwner -Value { Set-StrictMode -Off; Invoke-CimMethod -InputObject $this -MethodName GetOwner } }
                $o
            }
        }
        'Win32_OperatingSystem' {
            [pscustomobject]@{ Caption = 'Microsoft Windows 11 Pro'; Version = '10.0.26300'; BuildNumber = '26300'; CSName = $env:COMPUTERNAME
                LastBootUpTime = $s.LastBoot.ToLocalTime(); LocalDateTime = [datetime]::Now; OSArchitecture = '64-bit' }
        }
        default { Invoke-PsSmokeDeny $Name ('CIM class ' + $class + ' is not modeled') }
    }
}

function global:Invoke-PsSmokeNet {
    param([string]$Name, $Cmdlet, [hashtable]$Bound)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    foreach ($k in @('CimSession', 'AsJob', 'ThrottleLimit')) { if ($Bound.ContainsKey($k)) { Invoke-PsSmokeDeny $Name ('-' + $k + ' is not modeled') } }
    if ($Name -eq 'Test-NetConnection') {
        $computer = 'internetbeacon.msedge.net'
        if ($Bound.ContainsKey('ComputerName')) { $computer = [string]$Bound['ComputerName'] }
        if ($computer -notin @('localhost', '127.0.0.1', '::1')) { Invoke-PsSmokeDeny $Name ('non-loopback target ' + $computer) }
        $port = 0
        if ($Bound.ContainsKey('Port')) { $port = [int]$Bound['Port'] }
        $open = @($s.Listeners | Where-Object { [int]$_.port -eq $port }).Count -gt 0
        [PsToplevelSmoke.Policy]::Add('stub', $Name, $computer + ':' + $port + ' -> ' + $open)
        return [pscustomobject]@{ ComputerName = $computer; RemoteAddress = '127.0.0.1'; RemotePort = $port; TcpTestSucceeded = $open }
    }
    $sel = @($s.Listeners)
    if ($Bound.ContainsKey('LocalPort')) { $ports = @($Bound['LocalPort'] | ForEach-Object { [int]$_ }); $sel = @($sel | Where-Object { $ports -contains [int]$_.port }) }
    if ($Bound.ContainsKey('State')) { $states = @($Bound['State'] | ForEach-Object { [string]$_ }); if ($states -notcontains 'Listen') { $sel = @() } }
    if ($Bound.ContainsKey('OwningProcess')) { $owners = @($Bound['OwningProcess'] | ForEach-Object { [int]$_ }); $sel = @($sel | Where-Object { $owners -contains [int]$_.pid }) }
    if ($Bound.ContainsKey('LocalAddress')) { $addresses = @($Bound['LocalAddress'] | ForEach-Object { [string]$_ }); $sel = @($sel | Where-Object { $addresses -contains [string]$_.address }) }
    $keys = @($Bound.Keys | Where-Object { $_ -notin @('ErrorAction', 'WarningAction', 'InformationAction', 'ErrorVariable', 'WarningVariable', 'InformationVariable', 'OutVariable', 'OutBuffer', 'PipelineVariable', 'Verbose', 'Debug') } | Sort-Object)
    [PsToplevelSmoke.Policy]::Add('stub', $Name, (($keys | ForEach-Object { '-' + $_ + ' ' + (@($Bound[$_]) -join ',') }) -join ' ') + ' -> ' + $sel.Count)
    if ($sel.Count -eq 0) {
        $where = (($keys | ForEach-Object { '((' + $_ + ' = ' + (@($Bound[$_]) -join ',') + '))' }) -join ' AND ')
        Write-PsSmokeError $Cmdlet ([System.Management.Automation.ItemNotFoundException]::new('No matching MSFT_NetTCPConnection objects found by CIM query for instances of the ROOT/StandardCimv2/MSFT_NetTCPConnection class on the  CIM server: SELECT * FROM MSFT_NetTCPConnection  WHERE ' + $where + '. Verify query parameters and retry.')) 'CmdletizationQuery_NotFound' ([System.Management.Automation.ErrorCategory]::ObjectNotFound) $null
        return
    }
    foreach ($l in $sel) { [pscustomobject]@{ LocalAddress = [string]$l.address; LocalPort = [uint16]$l.port; RemoteAddress = '0.0.0.0'; RemotePort = [uint16]0; State = 'Listen'; OwningProcess = [uint32]$l.pid; AppliedSetting = $null } }
}

function global:Invoke-PsSmokeProcess {
    param([string]$Name, $Cmdlet, [hashtable]$Bound)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    foreach ($k in @('ComputerName', 'Module', 'FileVersionInfo', 'InputObject')) { if ($Bound.ContainsKey($k)) { Invoke-PsSmokeDeny $Name ('-' + $k + ' is not modeled') } }
    $withUser = $Bound.ContainsKey('IncludeUserName') -and [bool]$Bound['IncludeUserName']
    [PsToplevelSmoke.Policy]::Add('stub', $Name, (@($Bound.Keys) -join ','))
    if ($withUser -and -not $s.Elevated) {
        $Cmdlet.ThrowTerminatingError([System.Management.Automation.ErrorRecord]::new([System.InvalidOperationException]::new("The 'IncludeUserName' parameter requires elevated user rights. Try running the command again in a session that has been opened with elevated user rights (that is, Run as Administrator)."), 'IncludeUserNameRequiresElevation', [System.Management.Automation.ErrorCategory]::InvalidOperation, $null))
    }
    $sel = @($s.Processes)
    if ($Bound.ContainsKey('Id')) {
        $ids = @($Bound['Id'] | ForEach-Object { [int]$_ })
        foreach ($id in $ids) { if (@($sel | Where-Object { [int]$_.pid -eq $id }).Count -eq 0) { Write-PsSmokeError $Cmdlet ([System.Management.Automation.ItemNotFoundException]::new('Cannot find a process with the process identifier ' + $id + '.')) 'NoProcessFoundForGivenId' ([System.Management.Automation.ErrorCategory]::ObjectNotFound) $id } }
        $sel = @($sel | Where-Object { $ids -contains [int]$_.pid })
    }
    if ($Bound.ContainsKey('Name')) {
        $names = @($Bound['Name'] | ForEach-Object { [string]$_ })
        $sel = @($sel | Where-Object { $base = [System.IO.Path]::GetFileNameWithoutExtension([string]$_.name); @($names | Where-Object { $base -like $_ }).Count -gt 0 })
        if ($sel.Count -eq 0) { Write-PsSmokeError $Cmdlet ([System.Management.Automation.ItemNotFoundException]::new('Cannot find a process with the name "' + ($names -join ',') + '". Verify the process name and call the cmdlet again.')) 'NoProcessFoundForGivenName' ([System.Management.Automation.ErrorCategory]::ObjectNotFound) ($names -join ',') }
    }
    foreach ($p in $sel) {
        $visible = Test-PsSmokeVisible $p
        $o = [pscustomobject][ordered]@{ Id = [int]$p.pid; ProcessName = [System.IO.Path]::GetFileNameWithoutExtension([string]$p.name)
            Name = [System.IO.Path]::GetFileNameWithoutExtension([string]$p.name); Path = $(if ($visible) { $p.path } else { $null })
            StartTime = $(if ($visible) { (ConvertTo-PsSmokeDate $p.created_utc).ToLocalTime() } else { $null }); SessionId = [int]$p.session_id }
        if ($withUser) { $o | Add-Member -NotePropertyName UserName -NotePropertyValue $p.owner }
        $o
    }
}

function global:Get-PsSmokeTaskEntry {
    param([string]$Name)
    Set-StrictMode -Off
    $tasks = $global:PsSmoke.Tasks
    foreach ($k in $tasks.Keys) { if ($k -ne '*' -and [string]::Equals($k, $Name, [StringComparison]::OrdinalIgnoreCase)) { return , $tasks[$k] } }
    if ($tasks.ContainsKey('*')) { return , $tasks['*'] }
    'absent'
}

function global:Get-PsSmokeField {
    param($Object, [string]$Name, $Default)
    Set-StrictMode -Off
    if ($null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name] -and $null -ne $Object.$Name) { return $Object.$Name }
    $Default
}

function global:New-PsSmokeComTask {
    param([string]$Name, $Entry)
    Set-StrictMode -Off
    $principal = Get-PsSmokeField $Entry 'principal' $null
    $settings = Get-PsSmokeField $Entry 'settings' $null
    $actions = @()
    foreach ($a in @(Get-PsSmokeField $Entry 'actions' @())) {
        $actions += [pscustomobject]@{ Id = $null; Type = 0; Path = [string](Get-PsSmokeField $a 'path' ''); Arguments = [string](Get-PsSmokeField $a 'arguments' ''); WorkingDirectory = [string](Get-PsSmokeField $a 'working_directory' '') }
    }
    $triggers = @()
    foreach ($t in @(Get-PsSmokeField $Entry 'triggers' @())) {
        $triggers += [pscustomobject]@{ Id = $null; Type = [int](Get-PsSmokeField $t 'type' 9); Enabled = [bool](Get-PsSmokeField $t 'enabled' $false)
            UserId = [string](Get-PsSmokeField $t 'user_id' ''); Delay = [string](Get-PsSmokeField $t 'delay' ''); StartBoundary = [string](Get-PsSmokeField $t 'start_boundary' '')
            EndBoundary = [string](Get-PsSmokeField $t 'end_boundary' ''); ExecutionTimeLimit = [string](Get-PsSmokeField $t 'execution_time_limit' '')
            Repetition = [pscustomobject]@{ Interval = [string](Get-PsSmokeField $t 'repetition_interval' ''); Duration = [string](Get-PsSmokeField $t 'repetition_duration' ''); StopAtDurationEnd = $false } }
    }
    $definition = [pscustomobject]@{
        Actions = [PsToplevelSmoke.ComCollection]::new([object[]]$actions); Triggers = [PsToplevelSmoke.ComCollection]::new([object[]]$triggers)
        Principal = [pscustomobject]@{ Id = 'Author'; UserId = [string](Get-PsSmokeField $principal 'user_id' 'S-1-5-18'); LogonType = [int](Get-PsSmokeField $principal 'logon_type' 5); RunLevel = [int](Get-PsSmokeField $principal 'run_level' 1); GroupId = '' }
        Settings = [pscustomobject]@{ MultipleInstances = [int](Get-PsSmokeField $settings 'multiple_instances' 2); ExecutionTimeLimit = [string](Get-PsSmokeField $settings 'execution_time_limit' 'PT0S')
            RestartCount = [int](Get-PsSmokeField $settings 'restart_count' 0); RestartInterval = [string](Get-PsSmokeField $settings 'restart_interval' ''); AllowDemandStart = [bool](Get-PsSmokeField $settings 'allow_demand_start' $true)
            Enabled = [bool](Get-PsSmokeField $Entry 'enabled' $false); Hidden = $false; StartWhenAvailable = $false; DisallowStartIfOnBatteries = $false; StopIfGoingOnBatteries = $false }
        RegistrationInfo = [pscustomobject]@{ Description = [string](Get-PsSmokeField $Entry 'description' ''); Author = ''; URI = '\' + $Name; Date = '' }
        XmlText = [string](Get-PsSmokeField $Entry 'xml' ''); Data = ''
    }
    $count = [int](Get-PsSmokeField $Entry 'instances' 0)
    $instances = @()
    for ($i = 0; $i -lt $count; $i++) {
        $run = [pscustomobject]@{ InstanceGuid = '{00000000-0000-0000-0000-00000000000' + $i + '}'; Name = $Name; Path = '\' + $Name; State = 4; EnginePID = 0; CurrentAction = '' }
        $run | Add-Member -MemberType ScriptMethod -Name Stop -Value { Set-StrictMode -Off; Invoke-PsSmokeDeny 'Schedule.Service.RunningTask.Stop' 'ending a task is never stubbed' }
        $run | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
        $instances += $run
    }
    $task = [pscustomobject]@{ Name = $Name; Path = '\' + $Name; State = [int](Get-PsSmokeField $Entry 'state' 1); LastTaskResult = [int](Get-PsSmokeField $Entry 'last_task_result' 0)
        LastRunTime = [datetime]::new(2026, 10, 11); NextRunTime = [datetime]::new(1899, 12, 30); NumberOfMissedRuns = 0; Xml = [string](Get-PsSmokeField $Entry 'xml' '')
        Definition = $definition; PsSmokeEnabled = [bool](Get-PsSmokeField $Entry 'enabled' $false); PsSmokeInstances = [PsToplevelSmoke.ComCollection]::new([object[]]$instances)
        PsSmokeSddl = [string](Get-PsSmokeField $Entry 'sddl' 'D:P(A;;FA;;;SY)(A;;FA;;;BA)') }
    $task | Add-Member -MemberType ScriptProperty -Name Enabled -Value { $this.PsSmokeEnabled } -SecondValue { Set-StrictMode -Off; Invoke-PsSmokeDeny 'Schedule.Service.Task.Enabled' ('set ' + [string]$args[0]) }
    $task | Add-Member -MemberType ScriptMethod -Name GetInstances -Value { Set-StrictMode -Off; [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.Task.GetInstances', $this.Name + ' -> ' + $this.PsSmokeInstances.Count); , $this.PsSmokeInstances }
    $task | Add-Member -MemberType ScriptMethod -Name GetSecurityDescriptor -Value { Set-StrictMode -Off; [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.Task.GetSecurityDescriptor', $this.Name); $this.PsSmokeSddl }
    foreach ($m in @('Run', 'RunEx', 'Stop', 'SetSecurityDescriptor', 'GetRunTimes')) {
        $task | Add-Member -MemberType ScriptMethod -Name $m -Value ([scriptblock]::Create("Set-StrictMode -Off; Invoke-PsSmokeDeny 'Schedule.Service.Task.$m' 'task actions are never stubbed'"))
    }
    $task
}

function global:Get-PsSmokeComTask {
    param([string]$Name)
    Set-StrictMode -Off
    $entry = Get-PsSmokeTaskEntry $Name
    if ($entry -is [string]) {
        [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.Folder.GetTask', $Name + ' -> ' + $entry)
        if ($entry -eq 'denied') { throw [System.Runtime.InteropServices.COMException]::new('Access is denied. (Exception from HRESULT: 0x80070005 (E_ACCESSDENIED))', -2147024891) }
        throw [System.Runtime.InteropServices.COMException]::new('The system cannot find the file specified. (Exception from HRESULT: 0x80070002)', -2147024894)
    }
    [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.Folder.GetTask', $Name + ' -> readable')
    New-PsSmokeComTask $Name $entry
}

function global:New-PsSmokeTaskFolder {
    param([string]$Path)
    Set-StrictMode -Off
    $folder = [pscustomobject]@{ Name = $(if ($Path -eq '\') { '\' } else { $Path.TrimEnd('\').Split('\')[-1] }); Path = $Path }
    $folder | Add-Member -MemberType ScriptMethod -Name GetTask -Value { Set-StrictMode -Off; Get-PsSmokeComTask ([string]$args[0]) }
    $folder | Add-Member -MemberType ScriptMethod -Name GetFolder -Value { Set-StrictMode -Off; [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.Folder.GetFolder', [string]$args[0]); New-PsSmokeTaskFolder ([string]$args[0]) }
    $folder | Add-Member -MemberType ScriptMethod -Name GetTasks -Value {
        Set-StrictMode -Off
        [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.Folder.GetTasks', $this.Path)
        $list = @()
        foreach ($k in $global:PsSmoke.Tasks.Keys) { if ($k -ne '*' -and $global:PsSmoke.Tasks[$k] -isnot [string]) { $list += New-PsSmokeComTask $k $global:PsSmoke.Tasks[$k] } }
        , [PsToplevelSmoke.ComCollection]::new([object[]]$list)
    }
    foreach ($m in @('RegisterTaskDefinition', 'RegisterTask', 'DeleteTask', 'CreateFolder', 'DeleteFolder', 'SetSecurityDescriptor', 'GetSecurityDescriptor')) {
        $folder | Add-Member -MemberType ScriptMethod -Name $m -Value ([scriptblock]::Create("Set-StrictMode -Off; Invoke-PsSmokeDeny 'Schedule.Service.Folder.$m' 'task registration and folder access are never stubbed'"))
    }
    $folder
}

function global:New-PsSmokeScheduler {
    Set-StrictMode -Off
    $scheduler = [pscustomobject]@{ Connected = $false; TargetServer = $env:COMPUTERNAME; ConnectedUser = ''; ConnectedDomain = ''; HighestVersion = 65540 }
    $scheduler | Add-Member -MemberType ScriptMethod -Name Connect -Value {
        Set-StrictMode -Off
        if ($args.Count -gt 0 -and $args[0]) { Invoke-PsSmokeDeny 'Schedule.Service.Connect' ('remote server ' + [string]$args[0]) }
        [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.Connect', 'local'); $this.Connected = $true
    }
    $scheduler | Add-Member -MemberType ScriptMethod -Name GetFolder -Value { Set-StrictMode -Off; [PsToplevelSmoke.Policy]::Add('com', 'Schedule.Service.GetFolder', [string]$args[0]); New-PsSmokeTaskFolder ([string]$args[0]) }
    $scheduler | Add-Member -MemberType ScriptMethod -Name NewTask -Value { Set-StrictMode -Off; Invoke-PsSmokeDeny 'Schedule.Service.NewTask' 'task definitions are never created' }
    $scheduler
}

function global:Invoke-PsSmokeScheduled {
    param([string]$Name, $Cmdlet, [hashtable]$Bound)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    if ($Bound.ContainsKey('CimSession') -or $Bound.ContainsKey('AsJob')) { Invoke-PsSmokeDeny $Name 'remote or job scheduled-task queries are not modeled' }
    $names = @()
    if ($Bound.ContainsKey('TaskName')) { $names = @($Bound['TaskName'] | ForEach-Object { [string]$_ }) }
    elseif ($Bound.ContainsKey('InputObject')) { $names = @($Bound['InputObject'] | ForEach-Object { [string]$_.TaskName }) }
    else { foreach ($k in $s.Tasks.Keys) { if ($k -ne '*' -and $s.Tasks[$k] -isnot [string]) { $names += $k } } }
    foreach ($n in $names) {
        $entry = Get-PsSmokeTaskEntry $n
        [PsToplevelSmoke.Policy]::Add('stub', $Name, $n + ' -> ' + $(if ($entry -is [string]) { $entry } else { 'readable' }))
        if ($entry -is [string]) {
            if ($entry -eq 'denied') { Write-PsSmokeError $Cmdlet ([System.UnauthorizedAccessException]::new('Access is denied.')) 'HRESULT 0x80070005' ([System.Management.Automation.ErrorCategory]::PermissionDenied) $n }
            else { Write-PsSmokeError $Cmdlet ([System.Management.Automation.ItemNotFoundException]::new("No MSFT_ScheduledTask objects found with property 'TaskName' equal to '" + $n + "'.  Verify the value of the property and retry.")) 'CmdletizationQuery_NotFound_TaskName' ([System.Management.Automation.ErrorCategory]::ObjectNotFound) $n }
            continue
        }
        $stateName = @{ 0 = 'Unknown'; 1 = 'Disabled'; 2 = 'Queued'; 3 = 'Ready'; 4 = 'Running' }[[int](Get-PsSmokeField $entry 'state' 1)]
        if ($Name -eq 'Get-ScheduledTaskInfo') {
            [pscustomobject]@{ TaskName = $n; TaskPath = '\'; LastRunTime = [datetime]::new(2026, 10, 11); LastTaskResult = [int](Get-PsSmokeField $entry 'last_task_result' 0); NextRunTime = $null; NumberOfMissedRuns = 0 }
            continue
        }
        $com = New-PsSmokeComTask $n $entry
        [pscustomobject]@{ TaskName = $n; TaskPath = '\'; URI = '\' + $n; State = $stateName; Description = $com.Definition.RegistrationInfo.Description
            Actions = @($com.Definition.Actions | ForEach-Object { [pscustomobject]@{ Execute = $_.Path; Arguments = $_.Arguments; WorkingDirectory = $_.WorkingDirectory; Id = $null } })
            Triggers = @($com.Definition.Triggers); Principal = $com.Definition.Principal; Settings = $com.Definition.Settings }
    }
}

function global:Invoke-PsSmokeWeb {
    param([string]$Name, $Cmdlet, [hashtable]$Bound)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $uri = [System.Uri]([string]$Bound['Uri'])
    if ($uri.Host -notin @('127.0.0.1', 'localhost', '[::1]', '::1')) { Invoke-PsSmokeDeny $Name ('non-loopback URL ' + $uri.AbsoluteUri) }
    $hit = $null
    foreach ($k in $s.Http.Keys) { if ($uri.AbsoluteUri.StartsWith([string]$k, [StringComparison]::OrdinalIgnoreCase)) { $hit = $s.Http[$k]; break } }
    [PsToplevelSmoke.Policy]::Add('stub', $Name, $uri.AbsoluteUri + ' -> ' + $(if ($null -eq $hit) { 'connection refused' } else { [string](Get-PsSmokeField $hit 'status' 200) }))
    if ($null -eq $hit) {
        $Cmdlet.ThrowTerminatingError([System.Management.Automation.ErrorRecord]::new([System.Net.WebException]::new('Unable to connect to the remote server'), 'WebCmdletWebResponseException', [System.Management.Automation.ErrorCategory]::InvalidOperation, $uri))
    }
    $body = [string](Get-PsSmokeField $hit 'body' '')
    if ($Name -eq 'Invoke-RestMethod') { try { return ($body | ConvertFrom-Json) } catch { return $body } }
    [pscustomobject]@{ StatusCode = [int](Get-PsSmokeField $hit 'status' 200); StatusDescription = 'OK'; Content = $body; Headers = @{} }
}

function global:Invoke-PsSmokeStub {
    param([string]$Name, $Cmdlet, $Bound)
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $b = @{}
    foreach ($k in $Bound.Keys) { $b[$k] = $Bound[$k] }
    if ($b.ContainsKey('PsSmokeUnmodeled')) { Invoke-PsSmokeDeny $Name ('unmodeled arguments: ' + ((@($b['PsSmokeUnmodeled']) | ForEach-Object { [string]$_ }) -join ' ')) }
    switch ($Name) {
        { $_ -in @('Test-Path', 'Get-Item', 'Get-ChildItem', 'Get-Content', 'Get-FileHash', 'Get-Acl', 'Resolve-Path') } { Invoke-PsSmokeFs $Name $Cmdlet $b; break }
        { $_ -in @('Get-CimInstance', 'Invoke-CimMethod', 'Get-WmiObject') } { Invoke-PsSmokeCim $Name $Cmdlet $b; break }
        { $_ -in @('Get-NetTCPConnection', 'Test-NetConnection') } { Invoke-PsSmokeNet $Name $Cmdlet $b; break }
        'Get-Process' { Invoke-PsSmokeProcess $Name $Cmdlet $b; break }
        { $_ -in @('Get-ScheduledTask', 'Get-ScheduledTaskInfo') } { Invoke-PsSmokeScheduled $Name $Cmdlet $b; break }
        { $_ -in @('Invoke-RestMethod', 'Invoke-WebRequest') } { Invoke-PsSmokeWeb $Name $Cmdlet $b; break }
        'Start-Sleep' {
            $s.SleepCount = $s.SleepCount + 1
            $amount = ''
            if ($b.ContainsKey('Seconds')) { $amount = [string]$b['Seconds'] + 's' } elseif ($b.ContainsKey('Milliseconds')) { $amount = [string]$b['Milliseconds'] + 'ms' }
            if ($s.SleepCount -gt $s.SleepBudget) { Invoke-PsSmokeDeny $Name ('sleep budget of ' + $s.SleepBudget + ' exhausted (a plan-mode run should not poll)') }
            [PsToplevelSmoke.Policy]::Add('sleep', $Name, $amount + ' (not slept)')
            break
        }
        'Import-Module' {
            foreach ($k in @('Assembly', 'ModuleInfo', 'PSSession', 'CimSession', 'CimResourceUri', 'CimNamespace')) { if ($b.ContainsKey($k)) { Invoke-PsSmokeDeny $Name ('-' + $k + ' is not modeled') } }
            $names = @()
            if ($b.ContainsKey('Name')) { $names += @($b['Name']) }
            if ($b.ContainsKey('FullyQualifiedName')) { $names += @($b['FullyQualifiedName'] | ForEach-Object { if ($_ -is [hashtable]) { [string]$_['ModuleName'] } else { [string]$_ } }) }
            foreach ($n in $names) {
                $text = [string]$n
                $ok = $false
                if ([System.IO.Path]::IsPathRooted($text)) { $ok = [PsToplevelSmoke.Policy]::Under([System.IO.Path]::GetFullPath($text), $PSHOME) }
                elseif ($text -notmatch '[\\/]') { $ok = [System.IO.Directory]::Exists([System.IO.Path]::Combine($PSHOME, 'Modules', $text)) }
                if (-not $ok) { Invoke-PsSmokeDeny $Name ('module outside $PSHOME: ' + $text) }
                [PsToplevelSmoke.Policy]::Add('module', $Name, $text + ' (in-box; not imported, commands autoload)')
            }
            break
        }
        'New-Object' {
            if ($b.ContainsKey('ComObject')) {
                $prog = [string]$b['ComObject']
                if ($prog -ieq 'Schedule.Service') { [PsToplevelSmoke.Policy]::Add('com', 'New-Object', 'Schedule.Service (fake)'); New-PsSmokeScheduler; break }
                Invoke-PsSmokeDeny $Name ('COM object ' + $prog + ' is not modeled')
            }
            $type = [string]$b['TypeName']
            if ($type -match $s.NewObjectDeny) { Invoke-PsSmokeDeny $Name ('host-capable type ' + $type) }
            [PsToplevelSmoke.Policy]::Add('stub', $Name, $type + ' (pass-through)')
            & $s.Real[$Name] @b
            break
        }
        'Add-Type' {
            foreach ($k in @('Path', 'LiteralPath')) { if ($b.ContainsKey($k)) { foreach ($p in @($b[$k])) { if (-not [PsToplevelSmoke.Policy]::IsRealRoot([PsToplevelSmoke.Policy]::Key([string]$p))) { Invoke-PsSmokeDeny $Name ('assembly or source outside the read roots: ' + $p) } } } }
            $what = ''
            if ($b.ContainsKey('TypeDefinition')) { $what = ([string]$b['TypeDefinition']).Trim(); if ($what.Length -gt 160) { $what = $what.Substring(0, 160) } }
            elseif ($b.ContainsKey('AssemblyName')) { $what = 'AssemblyName ' + (@($b['AssemblyName']) -join ',') }
            [PsToplevelSmoke.Policy]::Add('add-type', $Name, $what)
            & $s.Real[$Name] @b
            break
        }
        default { Invoke-PsSmokeDeny $Name 'no stub handler' }
    }
}

function global:Invoke-PsSmokeNative {
    Set-StrictMode -Off
    $s = $global:PsSmoke
    $name = [string]$args[0]; $ruleKey = [string]$args[1]
    $rest = @()
    if ($args.Count -gt 2) { $rest = @($args[2..($args.Count - 1)] | ForEach-Object { [string]$_ }) }
    $joined = $rest -join ' '
    $rule = $null
    foreach ($candidate in @($s.Natives[$ruleKey])) {
        $pattern = [string]$candidate.match
        if (-not $pattern -or [regex]::IsMatch($joined, $pattern)) { $rule = $candidate; break }
    }
    if ($null -eq $rule) { Invoke-PsSmokeDeny $name ('no native rule matches: ' + $joined) }
    [PsToplevelSmoke.Policy]::Add('native', $name, $joined + ' -> exit ' + [int]$rule.exit)
    $global:LASTEXITCODE = [int]$rule.exit
    $s.LastNativeExit = [int]$rule.exit
    $out = [string]$rule.stdout
    if ($out) { foreach ($line in $out.TrimEnd("`n").Split("`n")) { $line.TrimEnd("`r") } }
    $err = [string]$rule.stderr
    if ($err) { foreach ($line in $err.TrimEnd("`n").Split("`n")) { Write-Error -ErrorRecord ([System.Management.Automation.ErrorRecord]::new([System.Management.Automation.RemoteException]::new($line.TrimEnd("`r")), 'NativeCommandError', [System.Management.Automation.ErrorCategory]::NotSpecified, $line)) } }
}

function global:New-PsSmokeFileCommand {
    # The Windows PowerShell 5.1 -File argument algorithm (CommandLineParameterParser), then a Command the way the console
    # host builds it: new Command(file, isScript false, useLocalScope false) with CommandParameter objects.
    $spec = $global:PsSmokeSpec
    $command = [System.Management.Automation.Runspaces.Command]::new($global:PsSmoke.Target, $false, $false)
    $pending = $null
    $dashes = @([char]0x2D, [char]0x2013, [char]0x2014, [char]0x2015)
    foreach ($raw in @($spec.args)) {
        $arg = [string]$raw
        if ($null -ne $pending) { $command.Parameters.Add([System.Management.Automation.Runspaces.CommandParameter]::new($pending, $arg)); $pending = $null; continue }
        if ($arg.Length -gt 0 -and $dashes -contains $arg[0]) {
            $offset = $arg.IndexOf(':')
            if ($offset -ge 0) {
                if ($offset -eq $arg.Length - 1) { $pending = $arg.TrimEnd(':') }
                else { $command.Parameters.Add([System.Management.Automation.Runspaces.CommandParameter]::new($arg.Substring(0, $offset), $arg.Substring($offset + 1))) }
            } else { $command.Parameters.Add([System.Management.Automation.Runspaces.CommandParameter]::new($arg)) }
        } else { $command.Parameters.Add([System.Management.Automation.Runspaces.CommandParameter]::new([NullString]::Value, $arg)) }
    }
    , $command
}

function global:Initialize-PsSmoke {
    $ErrorActionPreference = 'Stop'
    $spec = $global:PsSmokeSpec
    $result = $global:PsSmokeResult
    try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $realAdmin = ([System.Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
    $result.self_test.real_token_elevated = [bool]$realAdmin
    $result.self_test.real_identity = [string]$identity.Name
    $result.self_test.ps_version = [string]$PSVersionTable.PSVersion
    $result.self_test.is_64bit = [Environment]::Is64BitProcess
    if ($realAdmin) { $result.refused = 'refused: the token is elevated; .NET elevation checks cannot be stubbed, so a plan could take administrator branches'; return $false }
    if ($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -ne 5) { $result.refused = 'refused: Windows PowerShell 5.1 is required'; return $false }
    $target = [System.IO.Path]::GetFullPath([string]$spec.target)
    if (-not [System.IO.File]::Exists($target)) { $result.refused = 'refused: target not found: ' + $target; return $false }
    # The type shims come first: compiling the target (Get-Command, the run) caches its type names, so [IO.File] must
    # already resolve to the shim before anything parses the target for execution.
    Add-Type -TypeDefinition ([System.IO.File]::ReadAllText([string]$spec.shim_source_path)) -Language CSharp
    $accelerators = [psobject].Assembly.GetType('System.Management.Automation.TypeAccelerators')
    $accelerators::Add('IO.File', [PsToplevelSmoke.ShimFile])
    $accelerators::Add('Security.Principal.WindowsPrincipal', [PsToplevelSmoke.ShimPrincipal])
    $resolved = ([scriptblock]::Create('[IO.File].FullName + "|" + [Security.Principal.WindowsPrincipal].FullName')).InvokeReturnAsIs()
    $result.self_test.type_shims = $resolved
    if ($resolved -ne 'PsToplevelSmoke.ShimFile|PsToplevelSmoke.ShimPrincipal') { throw ('the type shims did not take effect: ' + $resolved) }
    # Defense in depth: no argument may bind -Apply or one of its aliases (ps_toplevel_smoke.py refuses first). The param
    # block is read from the AST only (no compilation).
    $applyNames = @('Apply')
    $tokens = $null; $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($target, [ref]$tokens, [ref]$parseErrors)
    $result.self_test.target_parse_errors = @($parseErrors).Count
    if ($null -ne $ast.ParamBlock) {
        foreach ($pa in $ast.ParamBlock.Parameters) {
            if ($pa.Name.VariablePath.UserPath -ne 'Apply') { continue }
            foreach ($at in $pa.Attributes) {
                if ($at -is [System.Management.Automation.Language.AttributeAst] -and $at.TypeName.Name -in @('Alias', 'AliasAttribute', 'System.Management.Automation.AliasAttribute')) {
                    foreach ($pos in $at.PositionalArguments) { foreach ($v in @($pos.SafeGetValue())) { $applyNames += [string]$v } }
                }
            }
        }
    }
    $result.self_test.apply_names = $applyNames
    $dashes = @([char]0x2D, [char]0x2013, [char]0x2014, [char]0x2015)
    foreach ($raw in @($spec.args)) {
        $arg = [string]$raw
        if ($arg.Length -lt 2 -or $dashes -notcontains $arg[0]) { continue }
        $n = $arg.Substring(1)
        $i = $n.IndexOf(':')
        if ($i -ge 0) { $n = $n.Substring(0, $i) }
        $n = $n.Trim()
        if (-not $n) { continue }
        foreach ($an in $applyNames) { if (([string]$an).StartsWith($n, [StringComparison]::OrdinalIgnoreCase)) { $result.refused = 'refused: ' + $arg + ' would bind -Apply'; return $false } }
    }
    # The policy the shim types share with the cmdlet stubs.
    $stub = $spec.stub
    $roots = [System.Collections.Generic.List[string]]::new()
    foreach ($r in @($stub.fs.read_roots)) { $roots.Add((ConvertTo-PsSmokeKey ([string]$r))) }
    [PsToplevelSmoke.Policy]::Configure($roots.ToArray(), [bool]$stub.host.elevated)
    $vfiles = [System.Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($prop in $stub.fs.virtual_file_map.PSObject.Properties) { $k = ConvertTo-PsSmokeKey $prop.Name; $vfiles[$k] = [string]$prop.Value; [PsToplevelSmoke.Policy]::MapFile($k, [string]$prop.Value) }
    $natives = @{}
    foreach ($prop in $stub.natives.PSObject.Properties) { $natives[$prop.Name.ToLowerInvariant()] = @($prop.Value) }
    $tasks = @{}
    foreach ($prop in $stub.tasks.PSObject.Properties) { $tasks[$prop.Name] = $prop.Value }
    $http = [ordered]@{}
    foreach ($prop in $stub.http.PSObject.Properties) { $http[$prop.Name] = $prop.Value }
    $pure = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($n in @($spec.pure)) { [void]$pure.Add([string]$n) }
    $allowed = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [void]$allowed.Add($target)
    $global:PsSmoke = @{
        Guard = $false; Depth = 0; Target = $target; AllowedScripts = $allowed; Stubs = @{}; Real = @{}; Pure = $pure
        Natives = $natives; Processes = @($stub.processes); Listeners = @($stub.listeners); Tasks = $tasks; Http = $http
        Roots = $roots.ToArray(); VirtualFiles = $vfiles; VirtualDirs = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        Elevated = [bool]$stub.host.elevated; User = [string]$stub.host.user; LastBoot = (ConvertTo-PsSmokeDate $stub.host.last_boot_utc)
        SleepCount = 0; SleepBudget = [int]$stub.sleep_budget; LastNativeExit = $null
        NewObjectDeny = '^(?i)((System\.)?(Net\.|Diagnostics\.(Process|EventLog)|ServiceProcess\.|Management\.|DirectoryServices\.|IO\.(FileStream|StreamWriter|FileSystemWatcher|Pipes\.)|Threading\.(Mutex|Semaphore|EventWaitHandle))|Microsoft\.Win32\.)'
        GuardErrorBlock = [scriptblock]::Create("throw [System.InvalidOperationException]::new('SmokeDenied: the smoke guard failed closed; nothing was executed.')")
    }
    foreach ($d in @($stub.fs.virtual_dirs)) { Add-PsSmokeDirChain (ConvertTo-PsSmokeKey ([string]$d)) $true }
    foreach ($k in $vfiles.Keys) { Add-PsSmokeDirChain $k $false }
    foreach ($r in $global:PsSmoke.Roots) { Add-PsSmokeDirChain $r $false }
    $env:COMPUTERNAME = [string]$stub.host.computer_name
    # Proxy functions with the real cmdlet metadata (types relaxed to [object] except switches) and known dynamic parameters.
    $table = [ordered]@{
        'Test-Path' = @('Microsoft.PowerShell.Management', '[object]${OlderThan}', '[object]${NewerThan}')
        'Get-Item' = @('Microsoft.PowerShell.Management', '[object]${Stream}')
        'Get-ChildItem' = @('Microsoft.PowerShell.Management', '[object]${Attributes}', '[switch]${Directory}', '[switch]${File}', '[switch]${Hidden}', '[switch]${ReadOnly}', '[switch]${System}')
        'Get-Content' = @('Microsoft.PowerShell.Management', '[object]${Delimiter}', '[object]${Encoding}', '[switch]${Raw}', '[object]${Stream}', '[switch]${Wait}')
        'Get-FileHash' = @('Microsoft.PowerShell.Utility'); 'Get-Acl' = @('Microsoft.PowerShell.Security'); 'Resolve-Path' = @('Microsoft.PowerShell.Management')
        'Get-CimInstance' = @('CimCmdlets'); 'Invoke-CimMethod' = @('CimCmdlets'); 'Get-WmiObject' = @('Microsoft.PowerShell.Management')
        'Get-Process' = @('Microsoft.PowerShell.Management'); 'Get-NetTCPConnection' = @('NetTCPIP'); 'Test-NetConnection' = @('NetTCPIP')
        'Get-ScheduledTask' = @('ScheduledTasks'); 'Get-ScheduledTaskInfo' = @('ScheduledTasks')
        'Invoke-RestMethod' = @('Microsoft.PowerShell.Utility'); 'Invoke-WebRequest' = @('Microsoft.PowerShell.Utility')
        'Start-Sleep' = @('Microsoft.PowerShell.Utility'); 'Import-Module' = @('Microsoft.PowerShell.Core')
        'New-Object' = @('Microsoft.PowerShell.Utility'); 'Add-Type' = @('Microsoft.PowerShell.Utility')
    }
    $generated = [System.Collections.Generic.List[string]]::new()
    foreach ($name in $table.Keys) {
        $entry = @($table[$name])
        $real = $null
        try { $real = Get-Command -Name ($entry[0] + '\' + $name) -ErrorAction Stop | Select-Object -First 1 } catch { $real = $null }
        if ($null -ne $real) {
            $md = [System.Management.Automation.CommandMetadata]::new($real)
            foreach ($pm in @($md.Parameters.Values)) { if ($pm.ParameterType -ne [System.Management.Automation.SwitchParameter]) { $pm.ParameterType = [object] } }
            $binding = [System.Management.Automation.ProxyCommand]::GetCmdletBindingAttribute($md)
            $params = [System.Management.Automation.ProxyCommand]::GetParamBlock($md)
            $extras = @()
            for ($i = 1; $i -lt $entry.Count; $i++) { $pname = ([regex]::Match($entry[$i], '\$\{(\w+)\}')).Groups[1].Value; if (-not $md.Parameters.ContainsKey($pname)) { $extras += $entry[$i] } }
            if ($extras.Count) { if ($params.Trim()) { $params = $params + ",`n" + ($extras -join ",`n") } else { $params = $extras -join ",`n" } }
            $s = $global:PsSmoke; $s.Real[$name] = $real; $generated.Add($name)
        } else {
            $binding = '[CmdletBinding()]'
            $params = '[Parameter(ValueFromRemainingArguments = $true)][object[]]${PsSmokeUnmodeled}'
        }
        # Inside the stub machinery (Depth > 0) a stub is the real command: a real cmdlet or module function the
        # machinery called (Get-FileHash calls Resolve-Path) must not be re-virtualized.
        $text = 'function global:' + $name + " {`n" + $binding + "`nparam(" + $params + ")`nprocess {`n" +
            "if (`$global:PsSmoke.Depth -gt 0 -and `$global:PsSmoke.Real.ContainsKey('" + $name + "')) { & `$global:PsSmoke.Real['" + $name + "'] @PSBoundParameters; return }`n" +
            "`$global:PsSmoke.Depth = `$global:PsSmoke.Depth + 1`n" +
            "try { `$PsSmokeOut = @(Invoke-PsSmokeStub '" + $name + "' `$PSCmdlet `$PSBoundParameters) } finally { `$global:PsSmoke.Depth = `$global:PsSmoke.Depth - 1 }`n" +
            "`$PsSmokeOut`n}`n}"
        . ([scriptblock]::Create($text))
        $global:PsSmoke.Stubs[$name] = Get-Command -Name $name -CommandType Function
    }
    $result.self_test.stubs_with_real_metadata = $generated.ToArray()
    $result.self_test.stubs = @($table.Keys)
    $true
}

$global:PsSmokePre = {
    param($name, $e)
    try {
        $s = $global:PsSmoke
        if (-not $s.Guard -or $s.Depth -gt 0 -or $s.Natives.Count -eq 0) { return }
        $key = ([string]$name).ToLowerInvariant()
        $rule = $null
        if ($s.Natives.ContainsKey($key)) { $rule = $key }
        else {
            $leaf = [System.IO.Path]::GetFileName($key)
            if ($s.Natives.ContainsKey($leaf)) { $rule = $leaf }
            elseif ($leaf.IndexOf('.') -lt 0 -and $s.Natives.ContainsKey($leaf + '.exe')) { $rule = $leaf + '.exe' }
        }
        if ($null -eq $rule) { return }
        $e.CommandScriptBlock = [scriptblock]::Create("Invoke-PsSmokeNative '" + ([string]$name).Replace("'", "''") + "' '" + $rule.Replace("'", "''") + "' @args")
    } catch { }
}

$global:PsSmokePost = {
    param($name, $e)
    try {
        $s = $global:PsSmoke
        if (-not $s.Guard -or $s.Depth -gt 0) { return }
        $c = $e.Command
        if ($null -eq $c) { return }
        if ($c -is [System.Management.Automation.AliasInfo]) { $resolvedCommand = $c.ResolvedCommand; if ($null -ne $resolvedCommand) { $c = $resolvedCommand } }
        $verdict = $null
        if ($c -is [System.Management.Automation.ExternalScriptInfo]) {
            if ($s.AllowedScripts.Contains([string]$c.Path)) { return }
            $verdict = 'external script'
        } elseif ($c -is [System.Management.Automation.ApplicationInfo]) {
            $verdict = 'native executable without a stub rule'
        } elseif ($c -is [System.Management.Automation.CmdletInfo]) {
            if ($s.Stubs.ContainsKey($c.Name)) { $e.Command = $s.Stubs[$c.Name]; return }
            if ($s.Pure.Contains($c.Name)) { return }
            $verdict = 'cmdlet outside the pure allow list'
        } elseif ($c -is [System.Management.Automation.FunctionInfo]) {
            if ($null -eq $c.Module) { return }
            if ($s.Stubs.ContainsKey($c.Name)) { $e.Command = $s.Stubs[$c.Name]; return }
            $verdict = 'module function (' + [string]$c.ModuleName + ')'
        } elseif ($c -is [System.Management.Automation.ScriptInfo]) {
            return
        } else {
            $verdict = 'command type ' + [string]$c.CommandType
        }
        [PsToplevelSmoke.Policy]::Add('denied', [string]$name, $verdict)
        $e.CommandScriptBlock = [scriptblock]::Create("throw [System.InvalidOperationException]::new('SmokeDenied: " + ([string]$name).Replace("'", "''") + ' (' + $verdict.Replace("'", "''") + "); nothing was executed.')")
    } catch {
        try { [PsToplevelSmoke.Policy]::Add('denied', [string]$name, 'guard error: ' + $_.Exception.Message) } catch { }
        $e.CommandScriptBlock = $global:PsSmoke.GuardErrorBlock
    }
}

try {
    $global:PsSmokeSpec = [System.IO.File]::ReadAllText($PsSmokeSpecPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    $global:PsSmokeResultPath = [string]$global:PsSmokeSpec.result_path
    if (Initialize-PsSmoke) {
        $ExecutionContext.InvokeCommand.PreCommandLookupAction = $global:PsSmokePre
        $ExecutionContext.InvokeCommand.PostCommandLookupAction = $global:PsSmokePost
        $global:PsSmokePreDelegate = $ExecutionContext.InvokeCommand.PreCommandLookupAction
        $global:PsSmokePostDelegate = $ExecutionContext.InvokeCommand.PostCommandLookupAction
        # Self-test under the target's usual StrictMode: a denied cmdlet must not run, a module-qualified stubbed cmdlet
        # must reach its stub. The self-test entries are removed from the trace afterwards.
        $before = [PsToplevelSmoke.Policy]::Trace.Count
        $global:PsSmoke.Guard = $true
        $probe = & { Set-StrictMode -Version Latest; $ErrorActionPreference = 'Stop'; try { $null = Invoke-Expression '1 + 1'; 'LEAKED' } catch { 'DENIED' } }
        $redirect = & { Set-StrictMode -Version Latest; $ErrorActionPreference = 'Stop'; Microsoft.PowerShell.Management\Test-Path -LiteralPath 'C:\PsToplevelSmokeSelfTest\absent' }
        $global:PsSmoke.Guard = $false
        $selfTrace = @([PsToplevelSmoke.Policy]::Trace | Select-Object -Skip $before | ForEach-Object { $_.kind + ' ' + $_.command })
        [PsToplevelSmoke.Policy]::Truncate($before)
        $global:PsSmokeResult.self_test.guard = $probe
        $global:PsSmokeResult.self_test.redirect = [string]$redirect + ' ' + ($selfTrace -join '; ')
        if ($probe -ne 'DENIED' -or $redirect -ne $false -or ($selfTrace -join ';') -notmatch 'fs-virtual Test-Path') { throw ('the command guard self-test failed: ' + $probe + ' / ' + $global:PsSmokeResult.self_test.redirect) }
        $global:PsSmokeReady = $true
        $global:PsSmokeResult.bootstrap_ok = $true
    }
} catch {
    $global:PsSmokeResult.bootstrap_error = [string]$_.Exception.Message + ' @ ' + [string]$_.InvocationInfo.PositionMessage
    $global:PsSmokeReady = $false
}

if ($global:PsSmokeReady) {
    # The target runs from the global scope (the console host's -File runs scripts there; '& script' gets its own scope).
    # Command mode records $? of the console line: a script stopped by an error leaves it False while the line goes on,
    # exactly as at a console; that error is then reported as the terminating one.
    $global:PsSmokeCommandOk = $null
    $global:PsSmokePs = [System.Management.Automation.PowerShell]::Create([System.Management.Automation.RunspaceMode]::CurrentRunspace)
    if ([string]$global:PsSmokeSpec.invocation -eq 'command') { [void]$global:PsSmokePs.AddScript([string]$global:PsSmokeSpec.command_text + "`n" + '$global:PsSmokeCommandOk = $?', $false) }
    else { [void]$global:PsSmokePs.Commands.AddCommand((New-PsSmokeFileCommand)) }
    $global:PsSmokeOut = [System.Management.Automation.PSDataCollection[psobject]]::new()
    $global:PsSmokeTerminating = $null
    $global:LASTEXITCODE = 23130
    $global:PsSmoke.Guard = $true
    try { [void]$global:PsSmokePs.Invoke($null, $global:PsSmokeOut) } catch { $global:PsSmokeTerminating = $_ } finally { $global:PsSmoke.Guard = $false }
    try {
        $global:PsSmokeResult.guard_intact = ([object]::ReferenceEquals($ExecutionContext.InvokeCommand.PreCommandLookupAction, $global:PsSmokePreDelegate) -and [object]::ReferenceEquals($ExecutionContext.InvokeCommand.PostCommandLookupAction, $global:PsSmokePostDelegate))
        $ExecutionContext.InvokeCommand.PreCommandLookupAction = $null
        $ExecutionContext.InvokeCommand.PostCommandLookupAction = $null
        $global:PsSmokeResult.output_count = $global:PsSmokeOut.Count
        if ($global:PsSmokeOut.Count) { $global:PsSmokeOut | Out-Default }
        $records = @($global:PsSmokePs.Streams.Error)
        foreach ($record in $records) { [Console]::Error.Write(($record | Out-String)) }
        $code = $global:LASTEXITCODE
        $exitStatement = ($null -ne $code -and $code -ne 23130 -and $code -ne $global:PsSmoke.LastNativeExit)
        $promoted = $null
        if ($null -eq $global:PsSmokeTerminating -and -not $exitStatement -and $global:PsSmokeCommandOk -eq $false -and $records.Count) {
            $promoted = $records[$records.Count - 1]
            $records = @($records | Select-Object -First ($records.Count - 1))
        }
        $errorsSeen = [System.Collections.Generic.List[object]]::new()
        foreach ($record in $records) { $errorsSeen.Add((ConvertTo-PsSmokeErrorInfo $record)) }
        $global:PsSmokeResult.non_terminating_errors = $errorsSeen.ToArray()
        if ($null -ne $global:PsSmokeTerminating) {
            $global:PsSmokeResult.terminating_error = ConvertTo-PsSmokeErrorInfo $global:PsSmokeTerminating.Exception
            $global:PsSmokeResult.exit_code = 1; $global:PsSmokeResult.exit_source = 'terminating_error'
            $x = $global:PsSmokeTerminating.Exception
            while ($x -is [System.Management.Automation.MethodInvocationException] -and $null -ne $x.InnerException) { $x = $x.InnerException }
            $shown = $global:PsSmokeTerminating
            if ($x -is [System.Management.Automation.IContainsErrorRecord]) { $shown = $x.ErrorRecord }
            [Console]::Error.Write(($shown | Out-String))
        } elseif ($null -ne $promoted) {
            $global:PsSmokeResult.terminating_error = ConvertTo-PsSmokeErrorInfo $promoted
            $global:PsSmokeResult.exit_code = 1; $global:PsSmokeResult.exit_source = 'command_line_failed'
        } elseif ($exitStatement) {
            $global:PsSmokeResult.exit_code = [int]$code; $global:PsSmokeResult.exit_source = 'exit_statement'
        } else {
            $global:PsSmokeResult.exit_code = 0; $global:PsSmokeResult.exit_source = 'completed'
        }
        $global:PsSmokeExit = [int]$global:PsSmokeResult.exit_code
    } catch {
        $global:PsSmokeResult.bootstrap_error = 'result collection failed: ' + [string]$_.Exception.Message
        $global:PsSmokeExit = 91
    }
} elseif ($global:PsSmokeResult.refused) {
    $global:PsSmokeExit = 92
}
try { Write-PsSmokeResult } catch { [Console]::Error.WriteLine('ps_toplevel_smoke: result write failed: ' + $_.Exception.Message); $global:PsSmokeExit = 93 }
'''
