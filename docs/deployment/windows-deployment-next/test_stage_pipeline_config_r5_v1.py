"""Inert Windows PowerShell 5.1 harness for stage-pipeline-config-r5-v1.ps1 (CONFIG-STAGER, r5 sitting stage S9, 2026-10-11).

Nothing here elevates, writes under C:\\Program Files or C:\\ProgramData, runs a Python parser, or touches a task, service,
WSL, Docker or a VM. The script's functions are extracted from its AST and dot-sourced into a throwaway powershell.exe
(Windows PowerShell 5.1) with every root redirected under tmp_path and every system call stubbed: the elevation probe
(Initialize-StagerHost), the protected-ancestry and ACL reads (Assert-ProtectedPath, Get-StagingAclSummary), the protected
descriptor applied at creation (New-StagingSecurity: a DACL-only descriptor that keeps the test user able to clean up),
Read-R3Control (no protection checks under tmp_path) and the r5 parser (Invoke-NativeJudged). The apply path is exercised
only at function level inside that sandbox. The script file itself is never run top level on the real host (deploy audit
B-F7): even the parameter refusals go through Invoke-StagePipelineConfigR5Entry loaded from the AST with the host calls
stubbed; the only top-level runs are the plan-mode smoke tests at the end, through ps_toplevel_smoke.py (stubbed host). The
real commissioned pipeline.json and the builder are read read-only to build fixtures and pins.
"""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import ps_toplevel_smoke as smoke

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'stage-pipeline-config-r5-v1.ps1'
RETARGET = ROOT / 'retarget-warden-r5.ps1'
BUILDER = ROOT / 'build-pipeline-config-r5-candidate.py'
CHECK_R3 = ROOT / 'check-worker-native-status-r3.ps1'
COPY_HELPER = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
PREDECESSOR = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\docs\evidence\windows-2026-10-09\continuation\owner-wrappers\stage_pipeline_config.ps1')
REAL_COMMISSIONED = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\pipeline.json')
REAL_COMMISSIONING_COPY = Path(r'C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json')
CONFIG_PIN = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
REAL_TARGET = r'C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json'
SDDL = 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'
PARSER_OK = '{"parser_valid":true,"worker_identities":6,"max_shared_slots":4,"knowledge_enabled":true}'
STATUS_KEYS = ['status', 'staged_path', 'staged_sha256', 'outcome', 'mode', 'receipt_path', 'target_state', 'exit_code', 'reason']
R4_DIR = 'Pipeline4.2.7-windows-20261009-r4'
R5_DIR = 'Pipeline4.2.7-windows-20261011-r5'
TARGET_DIR = 'WardenConfig4.2.7-windows-20261011-r5-v1'
RECEIPT_RE = re.compile(r'^staging-receipt-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.json$')
HELD_RE = re.compile(r'^staging-held-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.json$')
FIELDS = ['schema', 'mode', 'outcome', 'gates', 'chosen_bindings', 'effort_contracts', 'error', 'candidate_file', 'candidate_sha256',
          'candidate_length', 'commissioned_path', 'commissioned_sha256', 'evidence', 'builder']
AGY_ARGS = ['--agent', 'cochem-inference-only', '--input-format', 'stream-json', '--output-format', 'stream-json', '--model', '{model}',
            '--disable-slash-commands']
# The real r5 interpreter path a real decision.json names; write_build(base=...) rebinds it to the fixture r5 root.
R5_PYTHON_REAL = 'C:\\Program Files\\CoChem\\' + 'Pipeline4.2.7-windows-20261011-r5' + '\\.venv\\Scripts\\python.exe'


def ps(value) -> str:
    return str(value).replace("'", "''")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    return sha(Path(path).read_bytes())


def crlf_json(document, indent=2) -> bytes:
    return (json.dumps(document, indent=indent) + '\n').replace('\n', '\r\n').encode('ascii')


def _synthetic_commissioned() -> bytes:
    slots = {f'slot{i}': f'C:\\ProgramData\\CoChemPipeline427\\workers\\slot{i}' for i in range(1, 7)}
    workers = {f'slot{i}': {'name': f'CoChem422Worker{i}', 'credential_target': f'CoChem422/slot{i}'} for i in range(1, 7)}
    return crlf_json({
        'private_root': 'C:\\ProgramData\\CoChemPipeline427\\private', 'knowledge': {'enabled': True}, 'slot_roots': slots, 'workers': workers,
        'providers': {'codex': {'executable': 'codex.exe', 'model': 'gpt-x'}, 'claude': {'executable': 'claude.exe', 'model': 'claude-x'},
                      'gemini': {'executable': 'C:\\Program Files\\CoChem\\Native4.2.7-windows-20261006\\agy.exe', 'model': 'gemini-3.1-pro-preview',
                                 'arguments': None, 'protocol': 'gemini-json', 'subscription_probe': None, 'inference_only': None, 'effort_contracts': {},
                                 'integration_hold': {'state': 'verification_pending', 'finding_ids': ['AGY-AUTH']}}},
        'timeout_seconds': 1800.0,
        'routing': {'policy_version': 2, 'tiers': {
            '1-3': [{'model': 'gemini-3.8-flash', 'provider': 'gemini', 'reasoning_effort': None}, {'model': 'claude-x', 'provider': 'claude', 'reasoning_effort': None}],
            '4-6': [{'model': 'gemini-3.8-flash', 'provider': 'gemini', 'reasoning_effort': 'extended'}, {'model': 'gpt-x', 'provider': 'codex', 'reasoning_effort': 'low'}],
            '7-9': [{'model': 'gemini-3.1-pro-preview', 'provider': 'gemini', 'reasoning_effort': 'high'}, {'model': 'claude-x', 'provider': 'claude', 'reasoning_effort': 'high'}]}},
        'max_execution_slots': 4})


def _commissioned_bytes() -> bytes:
    # The real commissioned file (read-only) when present and pinned; a synthetic stand-in otherwise.
    try:
        data = REAL_COMMISSIONED.read_bytes()
    except OSError:
        return _synthetic_commissioned()
    return data if sha(data) == CONFIG_PIN else _synthetic_commissioned()


COMMISSIONED = _commissioned_bytes()
PIN = sha(COMMISSIONED)
BUILDER_SHA = sha256_file(BUILDER)


def builder_block(**changes) -> dict:
    """decision.json builder as build-pipeline-config-r5-candidate.py builder_info writes it (DROP removes a field)."""
    block = {'name': 'build-pipeline-config-r5-candidate.py', 'script_sha256': BUILDER_SHA, 'python': R5_PYTHON_REAL,
             'python_version': '3.12.13', 'isolated_mode': True, 'cochem_pipeline_file': None, 'cochem_pipeline_version_or_sha': None,
             'cochem_pipeline_modules_sha256': {}, 'import_error': None}
    for key, value in changes.items():
        if value is DROP:
            block.pop(key)
        else:
            block[key] = value
    return block


def mutate(change, indent=2, source=None) -> bytes:
    document = json.loads((source or COMMISSIONED).decode('utf-8'))
    change(document)
    return crlf_json(document, indent)


def contract_gemini(held: dict) -> dict:
    return {'executable': held['executable'], 'model': held['model'], 'arguments': list(AGY_ARGS), 'protocol': 'agy-stream-json',
            'identity_policy': 'reported-model-equality',
            'subscription_probe': {'arguments': ['--output-format', 'json', 'models'], 'protocol': 'json-fields',
                                   'expected': {'status': 'SUCCESS', 'command.name': 'models'}},
            'inference_only': {'arguments': list(AGY_ARGS), 'version_arguments': ['--version'],
                               'executable_sha256': '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741', 'version': '1.3.1',
                               'capability_reference': 'C:\\Program Files\\CoChem\\AgyIsolation4.2.7-windows-20261011-r4-v1\\isolation-receipt.json#' + 'a' * 64,
                               'disables_tools': True, 'disables_mcp': True, 'disables_hooks': True, 'disables_subagents': True, 'disables_model_fallback': True},
            'model_bindings': {'gemini-3.8-flash': 'gemini-3.8-flash-high'}, 'effort_contracts': {}}


def _set_contract(document):
    document['providers']['gemini'] = contract_gemini(document['providers']['gemini'])


CONTRACT = mutate(_set_contract)
OTHER_CONTRACT = mutate(lambda d: (_set_contract(d), d['providers']['gemini']['model_bindings'].__setitem__('gemini-3.8-flash', 'gemini-3.8-flash-low')))


class _Drop:
    pass


DROP = _Drop()


def make_decision(candidate: bytes, **changes) -> dict:
    """A builder decision.json as build-pipeline-config-r5-candidate.py writes it; changes override (DROP removes) any field."""
    contract = (changes['outcome'] == 'GEMINI_CONTRACT') if isinstance(changes.get('outcome'), str) else (candidate != COMMISSIONED)
    mode = changes.get('mode') if isinstance(changes.get('mode'), str) else 'attempt'
    reason = 'passed' if contract else ('not evaluated: held mode requested' if mode == 'held' else 'G1 slot3 is not REUSE_VERIFIED_SESSION')
    decision = {'schema': 'cochem-r5-config-decision/1', 'mode': mode, 'outcome': 'GEMINI_CONTRACT' if contract else 'GEMINI_HELD_COMMISSIONED_BYTES',
                'gates': {f'G{i}': {'pass': contract, 'reason': reason} for i in range(1, 7)},
                'chosen_bindings': {'gemini-3.8-flash': 'gemini-3.8-flash-high'} if contract else None,
                'effort_contracts': {} if contract else None, 'binding_selection': None, 'proposed': None, 'changed_paths': [],
                'error': None, 'candidate_file': 'pipeline.json', 'candidate_sha256': sha(candidate), 'candidate_length': len(candidate),
                'commissioned_path': str(REAL_COMMISSIONED), 'commissioned_sha256': PIN, 'commissioned_length': len(COMMISSIONED),
                'commissioned_pin': CONFIG_PIN, 'evidence': {'login': {'path': 'C:\\x\\series-complete.json', 'sha256': '1' * 64, 'bytes': 10}} if contract else {},
                'inputs': {'login_root': 'C:\\x', 'evidence_read': mode == 'attempt'}, 'evidence_binding': None,
                'builder': builder_block()}
    for key, value in changes.items():
        if value is DROP:
            decision.pop(key)
        else:
            decision[key] = value
    return decision


def decision_bytes(decision) -> bytes:
    return (json.dumps(decision, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode('ascii')


def r5_python(base: Path) -> Path:
    return base / R5_DIR / '.venv' / 'Scripts' / 'python.exe'


def write_build(directory: Path, candidate, decision, base=None) -> Path:
    """The builder's --out-dir: pipeline.json first, decision.json last (dict, raw bytes, or None for absent). With base, a
    decision whose builder.python names the real r5 interpreter names the fixture r5 interpreter under base instead."""
    directory.mkdir(parents=True, exist_ok=True)
    if candidate is not None:
        (directory / 'pipeline.json').write_bytes(candidate)
    if isinstance(decision, dict) and base is not None and isinstance(decision.get('builder'), dict) and decision['builder'].get('python') == R5_PYTHON_REAL:
        decision = dict(decision, builder=dict(decision['builder'], python=str(r5_python(base))))
    if decision is not None:
        (directory / 'decision.json').write_bytes(decision if isinstance(decision, bytes) else decision_bytes(decision))
    return directory


def make_r5(base: Path, name=R5_DIR, python_bytes=b'MZ fixture python (never executed)', after=None, raw_after=None) -> Path:
    root = base / name
    (root / '.venv' / 'Scripts').mkdir(parents=True, exist_ok=True)
    (root / '.venv' / 'Scripts' / 'python.exe').write_bytes(python_bytes)
    document = {'schema': 'cochem-stopped-runtime-update/1', 'mode': 'FRESH_STOPPED_RUNTIME_READY', 'target_root': str(root),
                'runtime_bindings': {'venv_python_sha256': sha(python_bytes)}}
    document.update(after or {})
    if raw_after is not None:
        (root / 'install-after.json').write_bytes(raw_after)
    elif raw_after is None and after != {'__absent__': True}:
        (root / 'install-after.json').write_text(json.dumps(document, indent=2), encoding='ascii')
    return root


def make_base(tmp_path: Path, name='CoChem', commissioned=COMMISSIONED, r5=True) -> Path:
    base = tmp_path / name
    (base / R4_DIR).mkdir(parents=True, exist_ok=True)
    (base / R4_DIR / 'pipeline.json').write_bytes(commissioned)
    if r5:
        make_r5(base)
    return base


PRELUDE = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($f in @($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]})){. ([scriptblock]::Create($f.Extent.Text))}
$script:real=@{};foreach($n in @('Set-StagerConstants','Get-StagingAclSummary','New-StagingSecurity','Import-StagerHelpers','Initialize-StagerHost','New-StagingRecordName')){$script:real[$n]=(Get-Item ('function:'+$n)).ScriptBlock}
$script:Attempt='v1';$script:scriptDirectory='__ROOT__'
& $script:real['Set-StagerConstants']
foreach($t in Import-ReviewedFunctions $script:copyHelper $script:copyHelperPin @('Assert-NoReparseAncestors','Initialize-FileIdentity','Open-VerifiedFile')){. ([scriptblock]::Create($t))}
foreach($t in Import-ReviewedFunctions $script:readHelper $script:readHelperPin @('Read-R3Text')){. ([scriptblock]::Create($t))}
Initialize-FileIdentity
$held=[Collections.Generic.List[IO.FileStream]]::new()
$script:calls=[Collections.Generic.List[string]]::new()
function Note {param([string]$Text)$script:calls.Add($Text)}
$script:unprotected=@{}
function Assert-ProtectedPath {param([string]$Path)Note ('protected:'+$Path);if($script:unprotected.ContainsKey($Path)){throw ('Untrusted protected owner: '+$Path)}}
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  Note ('r3:'+$Path)
  if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){throw ('Fixture control missing: '+$Path)}
  $bytes=[IO.File]::ReadAllBytes($Path);if($bytes.Length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $sha=[Security.Cryptography.SHA256]::Create();try{$actual=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
  if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  [pscustomobject]@{Stream=[IO.MemoryStream]::new($bytes);Sha256=$actual;Length=[long]$bytes.Length}}
$script:parserCode=0;$script:parserStdout='__PARSER_OK__';$script:nativeCalls=[Collections.Generic.List[object]]::new()
function Invoke-NativeJudged {param([string]$Executable,[string[]]$Arguments)Note ('native:'+$Executable);$script:nativeCalls.Add(@(@($Executable)+@($Arguments)));[pscustomobject]@{code=$script:parserCode;stdout=$script:parserStdout;stderr='stub stderr'}}
function New-AclRule {param([string]$Sid,[string]$Type='Allow',[long]$Rights=2032127,[bool]$Inherited=$false,[string]$Inheritance='None')[pscustomobject]@{sid=$Sid;type=$Type;rights=$Rights;inherited=$Inherited;inheritance=$Inheritance;propagation='None'}}
$script:goodAcl=[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@((New-AclRule 'S-1-5-18'),(New-AclRule 'S-1-5-32-544'))}
$script:wrongAcl=[pscustomobject]@{owner='S-1-5-21-1-2-3-1001';protected=$false;rules=@((New-AclRule 'S-1-5-32-545' 'Allow' 1179817))}
$script:badAcl=@{}
function Get-StagingAclSummary {param([string]$Path)Note ('acl:'+$Path);if($script:badAcl.ContainsKey($Path)){return $script:badAcl[$Path]};$script:goodAcl}
$script:userSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;$script:securityFails=$false
function New-StagingSecurity {param([bool]$Directory)Note ('security:'+$Directory)
  if($script:securityFails){throw 'The security identifier is not allowed to be the owner of this object.'}
  $i=$(if($Directory){'OICI'}else{''});$s=$(if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()})
  $s.SetSecurityDescriptorSddlForm('D:P(A;'+$i+';FA;;;SY)(A;'+$i+';FA;;;BA)(A;'+$i+';FA;;;'+$script:userSid+')');,$s}
$script:fixtureAdmin=$false;$script:fixtureUser='AETHERDESK\ansac';$script:fixtureBase='__BASE__';$script:fixturePin='__PIN__'
function Initialize-StagerHost {Note 'host';[pscustomobject]@{admin=$script:fixtureAdmin;name=$script:fixtureUser}}
function Import-StagerHelpers {Note 'helpers'}
function Set-StagerConstants {& $script:real['Set-StagerConstants'];Note 'constants'
  $script:base=$script:fixtureBase;$script:commissionedRoot=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4';$script:commissionedPath=Join-Path $script:commissionedRoot 'pipeline.json'
  $script:commissioningCopyPath=Join-Path $script:base 'WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json';$script:configPin=$script:fixturePin
  $script:targetRoot=Join-Path $script:base ('WardenConfig4.2.7-windows-'+$script:namespaceDate+'-r5-'+$script:Attempt);$script:targetPath=Join-Path $script:targetRoot 'pipeline.json'
  $script:r5ConfigPattern='^.+\\WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}\\pipeline\.json$'}
Set-StagerConstants;$script:calls.Clear()
function Invoke-Main {param([hashtable]$Arguments)
  $a=[ordered]@{BuildDirectory='';Apply=$false;Attempt='v1'};foreach($k in @($Arguments.Keys)){$a[$k]=$Arguments[$k]}
  $script:calls.Clear();$script:nativeCalls.Clear()
  $out=@(Invoke-StagePipelineConfigR5Main -Arguments $a -ScriptPath '__SCRIPT__' -ScriptDirectory '__ROOT__')
  $lines=@($out[-1].lines)
  [ordered]@{objects=$out.Count;exit_code=$out[-1].exit_code;document=($lines[0]|ConvertFrom-Json);status_line=$lines[-1];line_count=$lines.Count;
    calls=@($script:calls);native=@($script:nativeCalls|ForEach-Object {,@($_)})}}
'''


def _powershell(case: Path, timeout: int):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(case)], capture_output=True, text=True, timeout=timeout)


def run(tmp_path: Path, body: str, base=None, pin=PIN, timeout=240, prelude=None) -> dict:
    """Run PRELUDE + body in a throwaway Windows PowerShell 5.1 and parse the last JSON line it prints."""
    base = base if base is not None else tmp_path / 'CoChem'
    text = (prelude if prelude is not None else PRELUDE) + body
    text = (text.replace('__SCRIPT__', ps(SCRIPT)).replace('__ROOT__', ps(ROOT)).replace('__BASE__', ps(base)).replace('__PIN__', pin)
            .replace('__PARSER_OK__', ps(PARSER_OK)).replace('__RETARGET__', ps(RETARGET)))
    case = tmp_path / ('case-%d.ps1' % len(list(tmp_path.glob('case-*.ps1'))))
    case.write_text(text, encoding='utf-8-sig')
    result = _powershell(case, timeout)
    assert result.returncode == 0, (result.stdout[-4000:], result.stderr[-4000:])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stderr
    return json.loads(lines[-1])


def run_main(tmp_path: Path, arguments: str, setup: str = '', base=None) -> dict:
    value = run(tmp_path, setup + f"\nInvoke-Main {arguments}|ConvertTo-Json -Compress -Depth 14", base=base)
    value['status'] = json.loads(value['status_line'])
    return value


def snapshot(root: Path) -> dict:
    state = {}
    for path in sorted(root.rglob('*')):
        key = str(path.relative_to(root))
        if path.is_dir():
            state[key + os.sep] = None
        elif not path.name.startswith('case-'):
            info = path.stat()
            state[key] = (info.st_size, info.st_mtime_ns, sha256_file(path))
    return state


def listing(directory: Path) -> list:
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


# ----------------------------------------------------------------------------------------------- static checks

def test_script_is_ascii_without_bom_and_parses_under_windows_powershell_5_1(tmp_path):
    raw = SCRIPT.read_bytes()
    assert all(byte < 128 for byte in raw), [i for i, byte in enumerate(raw) if byte >= 128][:5]
    assert not raw.startswith(b'\xef\xbb\xbf')
    probe = tmp_path / 'parse.ps1'
    probe.write_text(f"$t=$null;$e=$null;$null=[Management.Automation.Language.Parser]::ParseFile('{ps(SCRIPT)}',[ref]$t,[ref]$e);"
                     "[ordered]@{errors=@($e).Count;major=$PSVersionTable.PSVersion.Major;edition=$PSVersionTable.PSEdition}|ConvertTo-Json -Compress", encoding='utf-8-sig')
    result = _powershell(probe, 60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {'errors': 0, 'major': 5, 'edition': 'Desktop'}


def test_only_top_level_statement_is_the_exit_entry_and_the_parameters_are_the_contract(tmp_path):
    make_base(tmp_path)
    value = run(tmp_path, r'''
      $other=@($ast.EndBlock.Statements|Where-Object {$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]})
      $names=@($ast.ParamBlock.Parameters|ForEach-Object {$_.Name.VariablePath.UserPath})
      $types=@($ast.ParamBlock.Parameters|ForEach-Object {$_.StaticType.Name})
      $nested=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)).Count-@($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]}).Count
      $validators=@($ast.ParamBlock.Parameters|ForEach-Object {@($_.Attributes|Where-Object {$_.TypeName.Name -like 'Validate*'}).Count}|Measure-Object -Sum).Sum
      [ordered]@{count=$other.Count;text=$(if($other.Count){$other[0].Extent.Text}else{''});params=$names;types=$types;nested=$nested;validators=$validators;
        begin=($null -ne $ast.BeginBlock);process=($null -ne $ast.ProcessBlock)}|ConvertTo-Json -Compress
    ''')
    assert value['count'] == 1 and value['text'] == ('exit (Invoke-StagePipelineConfigR5Entry -Arguments ([ordered]@{BuildDirectory=$BuildDirectory;'
                                                     'Apply=[bool]$Apply;Attempt=$Attempt}) -ScriptPath $PSCommandPath -ScriptDirectory $PSScriptRoot)'), value
    assert value['params'] == ['BuildDirectory', 'Apply', 'Attempt'] and value['types'] == ['String', 'SwitchParameter', 'String']
    assert value['nested'] == 0 and value['begin'] is False and value['process'] is False
    assert value['validators'] == 0, 'parameter rules run inside the script so every refusal has a documented exit code'


RETARGET_IDENTICAL = ['Import-ReviewedFunctions', 'Invoke-NativeJudged', 'Test-ExactBool', 'Test-ExactInt', 'Test-Sha256Text', 'Get-JsonMember',
                      'Get-R5RootCandidates', 'Find-R5Root', 'Invoke-R5ConfigParser', 'Assert-ApplyIdentity']


def test_functions_mirrored_from_retarget_are_byte_identical(tmp_path):
    make_base(tmp_path)
    value = run(tmp_path, r'''
      function Get-Texts {param($Path)$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);$m=@{};foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){$m[$f.Name]=$f.Extent.Text};$m}
      $mine=Get-Texts '__SCRIPT__';$theirs=Get-Texts '__RETARGET__'
      $diff=@();foreach($n in @(__LIST__)){if(-not $theirs.ContainsKey($n) -or $mine[$n] -cne $theirs[$n]){$diff+=$n}}
      [ordered]@{diff=$diff;count=$mine.Count}|ConvertTo-Json -Compress
    '''.replace('__LIST__', ','.join(f"'{n}'" for n in RETARGET_IDENTICAL)))
    assert value['diff'] == [], value


def test_static_safety_text_and_contract_strings():
    text = SCRIPT.read_text(encoding='ascii')
    for forbidden in ('Remove-Item', 'Move-Item', 'Copy-Item', 'Rename-Item', 'Set-Acl', 'Set-Content', 'Out-File', 'Add-Content', 'WriteAllBytes',
                      'WriteAllText', 'AppendAllText', 'FileMode]::Create)', 'FileMode]::Create,', 'FileMode]::OpenOrCreate', 'FileMode]::Truncate',
                      'FileMode]::Append', 'Start-Process', 'Stop-Process', 'schtasks', 'ScheduledTask', 'Schedule.Service', 'Invoke-Expression', 'RunAs',
                      'wsl', 'docker', 'Restart-', 'Stop-Service', 'taskkill', '.Delete(', 'robocopy', 'Invoke-WebRequest', '-Verb', 'ProgramData',
                      'Copy-VerifiedPayload', 'New-ProtectedDirectory', 'New-CodeAcl'):
        assert forbidden not in text, forbidden
    assert text.count('[IO.FileMode]::CreateNew') == 1, 'one CreateNew writer for the configuration, the receipt and the held record'
    assert text.count('DirectoryInfo]::new(') == 1 and '$directory.Create((New-StagingSecurity $true))' in text
    assert "$script:stagingSddl='" + SDDL + "'" in text and 'SetSecurityDescriptorSddlForm($script:stagingSddl)' in text
    for contract in ("'cochem-config-only-staging/2'", "'cochem-r5-config-decision/1'", "'cochem-config-only-staging-held/2'", "'cochem-config-only-staging-plan/2'",
                     "'cochem-config-only-staging-result/2'", "'GEMINI_HELD_COMMISSIONED_BYTES'", "'GEMINI_CONTRACT'", "'ALREADY_STAGED_IDENTICAL'", "'STAGED'",
                     "'PLAN_OK'", "'HELD'", "$script:namespaceDate='20261011'", "'WardenConfig4.2.7-windows-'", "'staging-receipt'", "'staging-held'",
                     f"$script:configPin='{CONFIG_PIN}'", "'Pipeline4.2.7-windows-20261009-r4'", "$ErrorActionPreference='Continue'"):
        assert contract in text, contract
    assert 'Get-DaemonHolds' not in text and 'GetTask(' not in text, 'staging a new file never reads or gates on task state (ARMY_ADDENDUM A1)'


def test_embedded_pins_match_the_files_on_disk():
    text = SCRIPT.read_text(encoding='ascii')
    assert f"$script:copyHelperPin='{sha256_file(COPY_HELPER)}'" in text
    assert f"$script:readHelperPin='{sha256_file(CHECK_R3)}'" in text
    assert f"$script:builderPin='{sha256_file(BUILDER)}'" in text, 'B-F2: the pinned builder is the builder on disk'
    assert f"$script:copyHelper='{COPY_HELPER}'" in text and "Join-Path $script:scriptDirectory 'check-worker-native-status-r3.ps1'" in text
    retarget = RETARGET.read_text(encoding='ascii')
    for name in ('r5ConfigPattern', 'r5RootPattern', 'namespaceDate', 'configPin'):
        mine = re.findall(r"\$script:" + name + r"='([^']*)'", text)
        theirs = re.findall(r"\$script:" + name + r"='([^']*)'", retarget)
        assert len(mine) == 1 and mine == theirs, (name, mine, theirs)
    assert PREDECESSOR.exists(), 'the repository predecessor named by the unit spec'
    present = [p for p in (REAL_COMMISSIONED, REAL_COMMISSIONING_COPY) if p.exists()]
    if not present:
        pytest.skip('the installed commissioned configuration is absent on this host')
    for path in present:
        assert sha256_file(path) == CONFIG_PIN, path


def test_real_constants_name_the_contract_paths(tmp_path):
    make_base(tmp_path)
    value = run(tmp_path, r'''
      $r=[ordered]@{}
      $script:Attempt='v1';& $script:real['Set-StagerConstants'];$r['v1']=$script:targetPath;$r['root_v1']=$script:targetRoot
      try{Assert-StagingTargetPath $script:targetPath;$r['v1_ok']=$true}catch{$r['v1_ok']=$_.Exception.Message}
      $script:Attempt='v7';& $script:real['Set-StagerConstants'];$r['v7']=$script:targetPath
      $r['commissioned']=$script:commissionedPath;$r['commissioned_root']=$script:commissionedRoot;$r['copy']=$script:commissioningCopyPath;$r['pin']=$script:configPin
      $r['pattern']=$script:r5ConfigPattern;$r['receipt']=(& $script:real['New-StagingRecordName'] 'staging-receipt');$r['held']=(& $script:real['New-StagingRecordName'] 'staging-held')
      $r['receipt_matches']=[bool]($r['receipt'] -cmatch $script:receiptNamePattern);$r['held_matches']=[bool]($r['held'] -cmatch $script:receiptNamePattern)
      $r['max']=$script:maxJsonBytes;$r['fields']=$script:decisionFields;$r['sddl']=$script:stagingSddl;$r['read_helper']=$script:readHelper
      $r|ConvertTo-Json -Compress
    ''')
    assert value['v1'] == REAL_TARGET and value['root_v1'] == str(Path(REAL_TARGET).parent) and value['v1_ok'] is True
    assert value['v7'] == REAL_TARGET.replace('-r5-v1', '-r5-v7')
    assert value['commissioned'] == str(REAL_COMMISSIONED) and value['commissioned_root'] == str(REAL_COMMISSIONED.parent)
    assert value['copy'] == str(REAL_COMMISSIONING_COPY) and value['pin'] == CONFIG_PIN and value['sddl'] == SDDL
    assert re.match(value['pattern'], REAL_TARGET) and not re.match(value['pattern'], str(REAL_COMMISSIONED))
    assert RECEIPT_RE.match(value['receipt']) and HELD_RE.match(value['held']) and value['receipt_matches'] is True and value['held_matches'] is False
    assert value['max'] == 1048576 and value['fields'] == FIELDS and value['read_helper'] == str(CHECK_R3)


def test_staging_security_is_the_house_sddl_for_directory_and_file(tmp_path):
    make_base(tmp_path)
    value = run(tmp_path, r'''
      $d=& $script:real['New-StagingSecurity'] $true;$f=& $script:real['New-StagingSecurity'] $false
      [ordered]@{directory=$d.GetSecurityDescriptorSddlForm('All');file=$f.GetSecurityDescriptorSddlForm('All');dtype=$d.GetType().Name;ftype=$f.GetType().Name;
        protected=$d.AreAccessRulesProtected;owner=$d.GetOwner([Security.Principal.SecurityIdentifier]).Value}|ConvertTo-Json -Compress
    ''')
    assert value == {'directory': SDDL, 'file': SDDL, 'dtype': 'DirectorySecurity', 'ftype': 'FileSecurity', 'protected': True, 'owner': 'S-1-5-32-544'}


def test_reviewed_helpers_are_imported_by_hash_and_a_changed_pin_is_refused(tmp_path):
    make_base(tmp_path)
    value = run(tmp_path, r'''
      . $script:real['Import-StagerHelpers']
      $defined=[ordered]@{};foreach($n in @('Assert-NoReparseAncestors','Assert-ProtectedPath','Initialize-FileIdentity','Open-VerifiedFile','Read-R3Control','Read-R3Text')){$defined[$n]=[bool](Get-Command $n -CommandType Function -ErrorAction SilentlyContinue)}
      $readControl=(Get-Item function:Read-R3Control).ScriptBlock.ToString()
      $script:copyHelperPin=('0'*64);$refused='';try{. $script:real['Import-StagerHelpers']}catch{$refused=$_.Exception.Message}
      [ordered]@{defined=$defined;protected=$readControl.Contains('Assert-ProtectedPath $Path');held=$readControl.Contains('$held.Add($stream)');refused=$refused}|ConvertTo-Json -Compress
    ''')
    assert all(value['defined'].values()), value['defined']
    assert value['protected'] is True and value['held'] is True
    assert value['refused'].startswith('Reviewed function source changed: ') and str(COPY_HELPER) in value['refused']


# ----------------------------------------------------------------------------------------------- parameters

def test_parameter_rules_are_pure_and_refuse_before_the_host(tmp_path):
    make_base(tmp_path)
    cases = {'ok': "@{BuildDirectory='C:\\x\\out\\';Attempt='v1'}", 'ok_v12': "@{BuildDirectory='C:\\x\\..\\y';Attempt='v12';Apply=$true}",
             'missing': "@{Attempt='v1'}", 'empty': "@{BuildDirectory='';Attempt='v1'}", 'relative': "@{BuildDirectory='out';Attempt='v1'}",
             'unc': "@{BuildDirectory='\\\\server\\share';Attempt='v1'}", 'forward': "@{BuildDirectory='C:/x';Attempt='v1'}",
             'stream': "@{BuildDirectory='C:\\x:stream';Attempt='v1'}", 'wildcard': "@{BuildDirectory='C:\\x\\*';Attempt='v1'}",
             'attempt_bad': "@{BuildDirectory='C:\\x';Attempt='v1000'}", 'attempt_upper': "@{BuildDirectory='C:\\x';Attempt='V1'}",
             'attempt_missing': "@{BuildDirectory='C:\\x'}"}
    lines = ['$r=[ordered]@{}']
    for case, arguments in cases.items():
        lines.append(f"try{{$r['{case}']=Assert-StagerParameters {arguments}}}catch{{$r['{case}']='REFUSED: '+$_.Exception.Message}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    value = run(tmp_path, '\n'.join(lines))
    assert value['ok'] == {'build_directory': 'C:\\x\\out', 'attempt': 'v1', 'apply': False}
    assert value['ok_v12'] == {'build_directory': 'C:\\y', 'attempt': 'v12', 'apply': True}
    for case in ('missing', 'empty'):
        assert value[case].startswith('REFUSED') and '-BuildDirectory <builder --out-dir> is required' in value[case]
    for case in ('relative', 'unc', 'forward', 'stream', 'wildcard'):
        assert value[case].startswith('REFUSED') and 'absolute local path' in value[case], case
    for case in ('attempt_bad', 'attempt_upper', 'attempt_missing'):
        assert value[case].startswith('REFUSED') and '-Attempt must be v' in value[case], case


ENTRY_REFUSALS = {
    'missing': ("[ordered]@{BuildDirectory='';Apply=$false;Attempt='v1'}", '-BuildDirectory <builder --out-dir> is required'),
    'relative': ("[ordered]@{BuildDirectory='relative\\out';Apply=$false;Attempt='v1'}", 'absolute local path'),
    'attempt': ("[ordered]@{BuildDirectory='__TMP__';Apply=$false;Attempt='v1000'}", '-Attempt must be v'),
    'apply_relative': ("[ordered]@{BuildDirectory='out';Apply=$true;Attempt='v1'}", 'absolute local path'),
}


def test_entry_from_the_ast_refuses_bad_parameters_with_exit_2_and_a_status_line(tmp_path):
    """Deploy audit B-F7: Invoke-StagePipelineConfigR5Entry, loaded from the AST with every host call stubbed (the script
    file is never run top level), prints the held document and the status line and returns 2 before any host call."""
    make_base(tmp_path)
    before = snapshot(tmp_path)
    lines = ['$r=[ordered]@{}']
    for name, (arguments, _) in ENTRY_REFUSALS.items():
        lines.append("$script:calls.Clear();$writer=[IO.StringWriter]::new();$console=[Console]::Out;[Console]::SetOut($writer)\n"
                     f"try{{$code=Invoke-StagePipelineConfigR5Entry -Arguments ({arguments.replace('__TMP__', ps(tmp_path))}) -ScriptPath '__SCRIPT__' -ScriptDirectory '__ROOT__'}}"
                     "finally{[Console]::SetOut($console)}\n"
                     f"$r['{name}']=[ordered]@{{code=$code;lines=@($writer.ToString() -split \"`r?`n\"|Where-Object {{$_}});calls=@($script:calls)}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 6')
    value = run(tmp_path, '\n'.join(lines))
    for name, (_, fragment) in ENTRY_REFUSALS.items():
        got = value[name]
        assert got['code'] == 2 and got['calls'] == [], (name, got)
        status = json.loads(got['lines'][-1])
        assert list(status) == STATUS_KEYS and status['status'] == 'HELD' and status['exit_code'] == 2 and status['staged_path'] is None
        assert fragment in status['reason'], (name, status)
        document = json.loads('\n'.join(got['lines'][:-1]))
        assert document['schema'] == 'cochem-config-only-staging-held/2' and document['phase'] == 'PARAMETERS' and document['changed'] is False
    assert snapshot(tmp_path) == before, 'a parameter refusal writes nothing'


def test_this_harness_never_runs_the_stager_script_top_level():
    """B-F7: every PowerShell child of this harness runs a generated case file; none names the stager with -File."""
    text = Path(__file__).read_text(encoding='ascii')
    for needle in ("'-File', " + "str(SCRIPT)", "-File " + "'{ps(SCRIPT)}'", "-File " + '"{SCRIPT}"', "& " + "'__SCRIPT__'"):
        assert needle not in text, needle
    assert text.count('subprocess.run' + '(') == 1 and "['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(case)]" in text


# ----------------------------------------------------------------------------------------------- decision.json

def _gates(**changes):
    gates = {f'G{i}': {'pass': True, 'reason': 'passed'} for i in range(1, 7)}
    gates.update(changes)
    return gates


def _renamed(decision, old, new):
    decision = dict(decision)
    decision[new] = decision.pop(old)
    return decision


# audit-build stager_provenance_repro.ps1: a GEMINI_CONTRACT decision whose builder block names no pinned builder, no r5
# interpreter and no isolated mode; the stager used to accept it.
FORGED_DECISION = {
    'schema': 'cochem-r5-config-decision/1', 'mode': 'attempt', 'outcome': 'GEMINI_CONTRACT',
    'gates': {f'G{i}': {'pass': True, 'reason': 'x'} for i in range(1, 7)},
    'chosen_bindings': {'gemini-3.8-flash': 'gemini-3.8-flash-high'}, 'effort_contracts': {}, 'error': None, 'candidate_file': 'pipeline.json',
    'candidate_sha256': '1' * 64, 'candidate_length': 100, 'commissioned_path': 'anything', 'commissioned_sha256': CONFIG_PIN,
    'evidence': {}, 'builder': {'python': 'C:\\Python314\\python.exe', 'isolated_mode': False, 'script_sha256': None}}


def decision_cases():
    held, contract = COMMISSIONED, CONTRACT
    d = make_decision
    gates_lower = _gates()
    gates_lower['g1'] = gates_lower.pop('G1')
    gates_no_g4 = _gates()
    gates_no_g4.pop('G4')
    cases = {
        'ok_held_mode_held': (held, d(held, mode='held'), None),
        'ok_held_mode_attempt': (held, d(held), None),
        'ok_contract': (contract, d(contract), None),
        'ok_extra_fields': (contract, d(contract, proposed={'x': 1}, changed_paths=['providers.gemini.protocol'], future_field=[1, 2]), None),
        'missing_decision': (held, None, 'decision.json is missing from the build directory'),
        'missing_build_directory': (None, None, 'The build directory does not exist'),
        'not_json': (held, b'{not json', 'decision.json is not JSON'),
        'bom': (held, b'\xef\xbb\xbf' + decision_bytes(d(held)), 'byte order mark'),
        'non_ascii': (held, json.dumps(d(held, error='caf\u00e9'), ensure_ascii=False).encode('utf-8'), 'not ASCII JSON'),
        'top_array': (held, b'[1,2]', 'not a JSON object'),
        'top_string': (held, b'"decision"', 'not a JSON object'),
        'wrong_schema': (held, d(held, schema='cochem-r5-config-decision/2'), 'schema is not cochem-r5-config-decision/1'),
        'schema_case_variant': (held, _renamed(d(held), 'schema', 'Schema'), 'lacks the required field schema'),
        'mode_case': (held, d(held, mode='Attempt'), 'mode must be attempt or held'),
        'mode_null': (held, d(held, mode=None), 'mode must be attempt or held'),
        'outcome_unknown': (held, d(held, outcome='GEMINI_ENABLED'), 'outcome must be GEMINI_CONTRACT or GEMINI_HELD_COMMISSIONED_BYTES'),
        'gates_array': (held, d(held, gates=[]), 'gates is not a JSON object'),
        'gate_missing_G4': (contract, d(contract, gates=gates_no_g4), 'gates lacks the gate object G4'),
        'gate_lowercase_g1': (contract, d(contract, gates=gates_lower), 'gates lacks the gate object G1'),
        'gate_pass_string': (contract, d(contract, gates=_gates(G2={'pass': 'true', 'reason': 'r'})), 'gate G2 must carry a boolean pass'),
        'gate_pass_int': (contract, d(contract, gates=_gates(G3={'pass': 1, 'reason': 'r'})), 'gate G3 must carry a boolean pass'),
        'gate_reason_null': (contract, d(contract, gates=_gates(G5={'pass': True, 'reason': None})), 'gate G5 must carry a boolean pass and a string reason'),
        'gate_reason_missing': (contract, d(contract, gates=_gates(G6={'pass': True})), 'gate G6 must carry'),
        'gate_not_object': (contract, d(contract, gates=_gates(G1=True)), 'gates lacks the gate object G1'),
        'bindings_array': (contract, d(contract, chosen_bindings=['gemini-3.8-flash']), 'chosen_bindings must be a JSON object or null'),
        'effort_string': (contract, d(contract, effort_contracts='none'), 'effort_contracts must be a JSON object or null'),
        'error_number': (held, d(held, error=1), 'error must be null or a string'),
        'candidate_file_number': (held, d(held, candidate_file=1), 'candidate_file must be a string'),
        'candidate_file_null': (held, d(held, candidate_file=None), 'candidate_file must be a string'),
        'sha_uppercase': (held, d(held, candidate_sha256=PIN.upper()), 'candidate_sha256 must be 64 lowercase hex'),
        'sha_short': (held, d(held, candidate_sha256=PIN[:63]), 'candidate_sha256 must be 64 lowercase hex'),
        'length_string': (held, d(held, candidate_length=str(len(held))), 'candidate_length must be an integer'),
        'length_float': (held, d(held, candidate_length=float(len(held))), 'candidate_length must be an integer'),
        'length_bool': (held, d(held, candidate_length=True), 'candidate_length must be an integer'),
        'length_zero': (held, d(held, candidate_length=0), 'candidate_length must be an integer from 1 to 1048576'),
        'length_too_big': (held, d(held, candidate_length=1048577), 'candidate_length must be an integer from 1 to 1048576'),
        'commissioned_path_blank': (held, d(held, commissioned_path='  '), 'commissioned_path must be a non-empty string'),
        'commissioned_path_number': (held, d(held, commissioned_path=7), 'commissioned_path must be a non-empty string'),
        'commissioned_sha_short': (held, d(held, commissioned_sha256='abc'), 'commissioned_sha256 must be 64 lowercase hex'),
        'evidence_null': (held, d(held, evidence=None), 'evidence must be a JSON object'),
        'evidence_array': (held, d(held, evidence=[]), 'evidence must be a JSON object'),
        'builder_string': (held, d(held, builder='x'), 'builder must be a JSON object'),
        # Deploy audit B-F2: builder provenance (the interpreter itself is compared with the bound r5 one later).
        'builder_not_isolated': (contract, d(contract, builder=builder_block(isolated_mode=False)), 'builder.isolated_mode must be true'),
        'builder_isolated_string': (contract, d(contract, builder=builder_block(isolated_mode='true')), 'builder.isolated_mode must be true'),
        'builder_isolated_missing': (held, d(held, builder=builder_block(isolated_mode=DROP)), 'builder.isolated_mode must be true'),
        'builder_sha_other': (contract, d(contract, builder=builder_block(script_sha256='0' * 64)), 'builder.script_sha256 is not the pinned builder ' + BUILDER_SHA),
        'builder_sha_upper': (held, d(held, builder=builder_block(script_sha256=BUILDER_SHA.upper())), 'builder.script_sha256 is not the pinned builder'),
        'builder_sha_null': (held, d(held, builder=builder_block(script_sha256=None)), 'builder.script_sha256 is not the pinned builder'),
        'builder_sha_missing': (contract, d(contract, builder=builder_block(script_sha256=DROP)), 'builder.script_sha256 is not the pinned builder'),
        'builder_sha_case_variant_name': (contract, d(contract, builder=_renamed(builder_block(), 'script_sha256', 'Script_sha256')),
                                          'builder.script_sha256 is not the pinned builder'),
        'builder_python_relative': (contract, d(contract, builder=builder_block(python='python.exe')), 'builder.python must be the absolute path'),
        'builder_python_missing': (held, d(held, builder=builder_block(python=DROP)), 'builder.python must be the absolute path'),
        'builder_python_number': (held, d(held, builder=builder_block(python=3)), 'builder.python must be the absolute path'),
        'audit_repro_forged_builder': (contract, FORGED_DECISION, 'builder.isolated_mode must be true'),
        'ok_other_interpreter_named': (contract, d(contract, builder=builder_block(python='C:\\Python314\\python.exe')), None),
    }
    for field in FIELDS:
        cases[f'missing_{field}'] = (held, d(held, **{field: DROP}), f'decision.json lacks the required field {field}.')
    return cases


def test_decision_json_is_checked_by_exact_name_type_and_encoding(tmp_path):
    make_base(tmp_path)
    cases = decision_cases()
    lines = ['$r=[ordered]@{}']
    for case, (candidate, decision, _) in cases.items():
        directory = tmp_path / 'decisions' / case
        if case != 'missing_build_directory':
            write_build(directory, candidate, decision)
        lines.append(f"try{{$d=Read-StagingDecision '{ps(directory)}';$r['{case}']=[ordered]@{{ok=$true;count=$d.chosen_bindings_count;passed=$d.gates_passed;"
                     f"sha=$d.sha256;length=$d.candidate_length;mode=$d.mode;outcome=$d.outcome;gates=$d.gates;path=$d.path}}}}"
                     f"catch{{$r['{case}']=[ordered]@{{ok=$false;message=$_.Exception.Message}}}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 6')
    value = run(tmp_path, '\n'.join(lines))
    for case, (_, _, expected) in cases.items():
        got = value[case]
        if expected is None:
            assert got['ok'] is True, (case, got)
        else:
            assert got['ok'] is False and expected in got['message'], (case, got)
    contract = value['ok_contract']
    assert contract['count'] == 1 and contract['passed'] == 6 and contract['outcome'] == 'GEMINI_CONTRACT' and contract['mode'] == 'attempt'
    assert contract['sha'] == sha256_file(tmp_path / 'decisions' / 'ok_contract' / 'decision.json') and contract['length'] == len(CONTRACT)
    assert list(contract['gates']) == ['G1', 'G2', 'G3', 'G4', 'G5', 'G6'] and contract['gates']['G1'] == {'pass': True, 'reason': 'passed'}
    held = value['ok_held_mode_held']
    assert held['count'] == 0 and held['passed'] == 0 and held['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and held['mode'] == 'held'
    assert held['path'] == str(tmp_path / 'decisions' / 'ok_held_mode_held' / 'decision.json')


def candidate_cases():
    contract = CONTRACT
    d = make_decision
    other = contract[:-3] + b'  \n' if contract.endswith(b'\r\n') else contract[:-2] + b'  '
    big = b'{' + b' ' * 1048575 + b'}'
    cases = {
        'ok': (contract, d(contract), None),
        'traversal_parent': (contract, d(contract, candidate_file='..\\pipeline.json'), 'candidate_file must be exactly pipeline.json'),
        'traversal_slash': (contract, d(contract, candidate_file='../pipeline.json'), 'candidate_file must be exactly pipeline.json'),
        'subdirectory': (contract, d(contract, candidate_file='sub\\pipeline.json'), 'candidate_file must be exactly pipeline.json'),
        'absolute': (contract, d(contract, candidate_file='C:\\Program Files\\CoChem\\x\\pipeline.json'), 'candidate_file must be exactly pipeline.json'),
        'upper_case': (contract, d(contract, candidate_file='PIPELINE.JSON'), 'candidate_file must be exactly pipeline.json'),
        'trailing_space': (contract, d(contract, candidate_file='pipeline.json '), 'candidate_file must be exactly pipeline.json'),
        'stream_name': (contract, d(contract, candidate_file='pipeline.json:x'), 'candidate_file must be exactly pipeline.json'),
        'empty_name': (contract, d(contract, candidate_file=''), 'candidate_file must be exactly pipeline.json'),
        'decision_file': (contract, d(contract, candidate_file='decision.json'), 'candidate_file must be exactly pipeline.json'),
        'missing_candidate': (None, d(contract), 'The candidate pipeline.json is missing from the build directory'),
        'sha_mismatch': (contract, d(contract, candidate_sha256=sha(other)), 'differs from decision.json candidate_sha256'),
        'length_mismatch': (contract, d(contract, candidate_length=len(contract) + 1), 'differs from decision.json candidate_length'),
        'too_large': (big + b' ', d(big, candidate_length=1048576), 'File exceeds 1048576 bytes'),
    }
    assert len(other) == len(contract) and other != contract
    return cases


def test_candidate_is_build_directory_pipeline_json_verified_by_length_and_sha(tmp_path):
    make_base(tmp_path)
    cases = candidate_cases()
    lines = ['$r=[ordered]@{}']
    for case, (candidate, decision, _) in cases.items():
        directory = write_build(tmp_path / 'candidates' / case, candidate, decision)
        lines.append(f"try{{$d=Read-StagingDecision '{ps(directory)}';$c=Read-StagingCandidate '{ps(directory)}' $d;"
                     f"$r['{case}']=[ordered]@{{ok=$true;sha=$c.sha256;length=$c.length;path=$c.path;bytes=$c.bytes.Length;same=($c.Stream -is [IO.FileStream])}}}}"
                     f"catch{{$r['{case}']=[ordered]@{{ok=$false;message=$_.Exception.Message}}}}")
    lines.append(f"$writeDenied=$false;try{{[IO.File]::AppendAllText('{ps(tmp_path / 'candidates' / 'ok' / 'pipeline.json')}','x')}}catch{{$writeDenied=$true}};$r['write_denied_while_held']=$writeDenied")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    value = run(tmp_path, '\n'.join(lines))
    for case, (_, _, expected) in cases.items():
        got = value[case]
        if expected is None:
            assert got['ok'] is True, (case, got)
        else:
            assert got['ok'] is False and expected in got['message'], (case, got)
    assert value['ok']['sha'] == sha(CONTRACT) and value['ok']['length'] == len(CONTRACT) and value['ok']['bytes'] == len(CONTRACT) and value['ok']['same'] is True
    assert value['ok']['path'] == str(tmp_path / 'candidates' / 'ok' / 'pipeline.json')
    assert value['write_denied_while_held'] is True, 'the verified candidate is held behind a deny-write handle for the whole run'
    assert sha256_file(tmp_path / 'candidates' / 'ok' / 'pipeline.json') == sha(CONTRACT)


def test_commissioned_pin_is_enforced_in_decision_json_and_on_disk(tmp_path):
    base = make_base(tmp_path)
    altered = tmp_path / 'altered' / 'pipeline.json'
    altered.parent.mkdir()
    altered.write_bytes(COMMISSIONED + b' ')
    body = f'''
      $r=[ordered]@{{}}
      $ok=Read-CommissionedReference ([ordered]@{{commissioned_sha256=$script:configPin;commissioned_path='C:\\builder\\pipeline.json'}})
      $r['ok']=[ordered]@{{sha=$ok.sha256;length=$ok.length;path=$ok.path;decision_path=$ok.decision_path;text_length=$ok.text.Length}}
      try{{$null=Read-CommissionedReference ([ordered]@{{commissioned_sha256=('1'*64);commissioned_path='x'}});$r['decision_pin']='accepted'}}catch{{$r['decision_pin']=$_.Exception.Message}}
      $script:commissionedPath='{ps(altered)}'
      try{{$null=Read-CommissionedReference ([ordered]@{{commissioned_sha256=$script:configPin;commissioned_path='x'}});$r['disk_altered']='accepted'}}catch{{$r['disk_altered']=$_.Exception.Message}}
      $script:commissionedPath='{ps(tmp_path / 'absent' / 'pipeline.json')}'
      try{{$null=Read-CommissionedReference ([ordered]@{{commissioned_sha256=$script:configPin;commissioned_path='x'}});$r['disk_missing']='accepted'}}catch{{$r['disk_missing']=$_.Exception.Message}}
      $r|ConvertTo-Json -Compress -Depth 4
    '''
    value = run(tmp_path, body)
    assert value['ok'] == {'sha': PIN, 'length': len(COMMISSIONED), 'path': str(base / R4_DIR / 'pipeline.json'), 'decision_path': 'C:\\builder\\pipeline.json',
                           'text_length': value['ok']['text_length']} and value['ok']['text_length'] > 100
    assert 'decision.json commissioned_sha256 is not the commissioned pin ' + PIN in value['decision_pin']
    assert 'does not verify against the pin' in value['disk_altered'] and 'Source digest changed' in value['disk_altered']
    assert 'does not verify against the pin' in value['disk_missing']


OUTCOME_CASES = {
    # case: (outcome, mode, candidate is commissioned, failed gates, error, bindings, expected refusal or None)
    'held_mode_held': ('GEMINI_HELD_COMMISSIONED_BYTES', 'held', True, [], None, 0, None),
    'held_attempt_failed_gates': ('GEMINI_HELD_COMMISSIONED_BYTES', 'attempt', True, ['G1', 'G5'], None, 0, None),
    'held_with_builder_error': ('GEMINI_HELD_COMMISSIONED_BYTES', 'attempt', True, ['G1'], 'RuntimeError: x', 0, None),
    'held_with_contract_bytes': ('GEMINI_HELD_COMMISSIONED_BYTES', 'attempt', False, ['G2'], None, 0, 'says GEMINI_HELD_COMMISSIONED_BYTES but the candidate is not the commissioned bytes'),
    'held_mode_held_contract_bytes': ('GEMINI_HELD_COMMISSIONED_BYTES', 'held', False, ['G2'], None, 0, 'is not the commissioned bytes'),
    'contract_ok': ('GEMINI_CONTRACT', 'attempt', False, [], None, 2, None),
    'contract_with_commissioned_bytes': ('GEMINI_CONTRACT', 'attempt', True, [], None, 1, 'says GEMINI_CONTRACT but the candidate is the commissioned bytes'),
    'contract_mode_held': ('GEMINI_CONTRACT', 'held', False, [], None, 1, 'GEMINI_CONTRACT requires decision mode attempt'),
    'contract_failed_G3': ('GEMINI_CONTRACT', 'attempt', False, ['G3'], None, 1, 'failed: G3.'),
    'contract_failed_G1_G6': ('GEMINI_CONTRACT', 'attempt', False, ['G1', 'G6'], None, 1, 'failed: G1, G6.'),
    'contract_error_set': ('GEMINI_CONTRACT', 'attempt', False, [], 'InvariantError: x', 1, 'GEMINI_CONTRACT requires error null'),
    'contract_empty_bindings': ('GEMINI_CONTRACT', 'attempt', False, [], None, 0, 'GEMINI_CONTRACT requires non-empty chosen_bindings'),
}


def test_outcome_mode_gates_and_bytes_must_agree(tmp_path):
    make_base(tmp_path)
    lines = ['$r=[ordered]@{}']
    for case, (outcome, mode, same, failed, error, bindings, _) in OUTCOME_CASES.items():
        gates = ';'.join(f"G{i}=[ordered]@{{pass=${'false' if f'G{i}' in failed else 'true'};reason='r'}}" for i in range(1, 7))
        error_ps = '$null' if error is None else f"'{ps(error)}'"
        candidate = '$script:configPin' if same else "('e'*64)"
        lines.append(f"$d=[ordered]@{{outcome='{outcome}';mode='{mode}';gates=[ordered]@{{{gates}}};error={error_ps};chosen_bindings_count={bindings}}}")
        lines.append(f"try{{Assert-OutcomeConsistency $d {candidate};$r['{case}']=''}}catch{{$r['{case}']=$_.Exception.Message}}")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    for case, spec in OUTCOME_CASES.items():
        expected = spec[-1]
        assert (value[case] == '') if expected is None else (expected in value[case]), (case, value[case])


# ----------------------------------------------------------------------------------------------- builder provenance (deploy audit B-F2)

def test_audit_repro_forged_builder_block_is_refused_by_the_decision_contract(tmp_path):
    """Port of audit-build stager_provenance_repro.ps1: the same functions from the AST, the same forged GEMINI_CONTRACT
    decision. It used to print ACCEPTED; Assert-DecisionDocument now refuses it before Assert-OutcomeConsistency."""
    make_base(tmp_path)
    forged = json.dumps(FORGED_DECISION)
    value = run(tmp_path, f'''
      $doc='{ps(forged)}'|ConvertFrom-Json;$result=[ordered]@{{accepted=$false;message=''}}
      try{{$summary=Assert-DecisionDocument $doc;Assert-OutcomeConsistency $summary ('1'*64);$result.accepted=$true}}catch{{$result.message=$_.Exception.Message}}
      $result|ConvertTo-Json -Compress''')
    assert value == {'accepted': False, 'message': 'decision.json builder.isolated_mode must be true: the builder runs only as <r5 python> -I.'}


BINDINGS_CASES = {
    # case: (outcome, decision chosen_bindings, candidate model_bindings (None: absent), expected refusal or None)
    'equal': ('GEMINI_CONTRACT', {'gemini-3.8-flash': 'gemini-3.8-flash-high'}, {'gemini-3.8-flash': 'gemini-3.8-flash-high'}, None),
    'equal_any_member_order': ('GEMINI_CONTRACT', {'gemini-3.8-flash:extended': {'reports': 'gemini-3.8-flash-high', 'argv': 'gemini-3.8-flash'},
                                                   'gemini-3.8-flash': 'gemini-3.8-flash-low'},
                               {'gemini-3.8-flash': 'gemini-3.8-flash-low', 'gemini-3.8-flash:extended': {'argv': 'gemini-3.8-flash', 'reports': 'gemini-3.8-flash-high'}}, None),
    'other_slug': ('GEMINI_CONTRACT', {'gemini-3.8-flash': 'gemini-3.8-flash-low'}, {'gemini-3.8-flash': 'gemini-3.8-flash-high'}, 'chosen_bindings differs'),
    'slug_case': ('GEMINI_CONTRACT', {'gemini-3.8-flash': 'Gemini-3.8-flash-high'}, {'gemini-3.8-flash': 'gemini-3.8-flash-high'}, 'chosen_bindings differs'),
    'route_case': ('GEMINI_CONTRACT', {'Gemini-3.8-flash': 'gemini-3.8-flash-high'}, {'gemini-3.8-flash': 'gemini-3.8-flash-high'}, 'chosen_bindings differs'),
    'extra_route': ('GEMINI_CONTRACT', {'gemini-3.8-flash': 'x', 'gemini-3.8-flash:extended': 'x'}, {'gemini-3.8-flash': 'x'}, 'chosen_bindings differs'),
    'missing_route': ('GEMINI_CONTRACT', {'gemini-3.8-flash': 'x'}, {'gemini-3.8-flash': 'x', 'gemini-3.8-flash:extended': 'x'}, 'chosen_bindings differs'),
    'string_vs_object': ('GEMINI_CONTRACT', {'gemini-3.8-flash': 'gemini-3.8-flash-high'},
                         {'gemini-3.8-flash': {'argv': 'gemini-3.8-flash-high', 'reports': 'gemini-3.8-flash-high'}}, 'chosen_bindings differs'),
    'nested_differs': ('GEMINI_CONTRACT', {'r': {'argv': 'a', 'reports': 'b'}}, {'r': {'argv': 'a', 'reports': 'c'}}, 'chosen_bindings differs'),
    'candidate_without_bindings': ('GEMINI_CONTRACT', {'gemini-3.8-flash': 'x'}, None, 'the candidate providers.gemini has no model_bindings object'),
    'held_outcome_is_not_compared': ('GEMINI_HELD_COMMISSIONED_BYTES', None, None, None),
}


def test_contract_chosen_bindings_must_equal_the_candidate_model_bindings(tmp_path):
    make_base(tmp_path)
    lines = ['$r=[ordered]@{}']
    for case, (outcome, chosen, bindings, _) in BINDINGS_CASES.items():
        document = json.loads(COMMISSIONED)
        _set_contract(document)
        if bindings is None:
            document['providers']['gemini'].pop('model_bindings')
        else:
            document['providers']['gemini']['model_bindings'] = bindings
        candidate_text = json.dumps(document)
        lines.append(f"$d=[ordered]@{{outcome='{outcome}';chosen_bindings=('{ps(json.dumps(chosen))}'|ConvertFrom-Json)}}")
        lines.append(f"try{{Assert-DecisionBindings $d '{ps(candidate_text)}';$r['{case}']=''}}catch{{$r['{case}']=$_.Exception.Message}}")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    for case, (_, _, _, expected) in BINDINGS_CASES.items():
        assert (value[case] == '') if expected is None else (expected in value[case]), (case, value[case])


def test_builder_interpreter_must_be_the_bound_r5_interpreter(tmp_path):
    make_base(tmp_path)
    bound = 'C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261011-r5\\.venv\\Scripts\\python.exe'
    cases = {'same': (bound, None), 'other_case': (bound.upper(), None), 'dot_segments': (bound.replace('\\.venv', '\\x\\..\\.venv'), None),
             'global_python': ('C:\\Python314\\python.exe', 'is not the bound r5 interpreter'),
             'r4_interpreter': (bound.replace('20261011-r5', '20261009-r4'), 'is not the bound r5 interpreter'),
             'base_toolchain': ('C:\\Program Files\\CoChem\\Toolchain4.2.7-windows-20261006\\Python312\\python.exe', 'is not the bound r5 interpreter'),
             'bad_path': ('C:\\a\\b|c', 'is not a usable path')}
    lines = ['$r=[ordered]@{}', f"$runtime=[ordered]@{{python='{ps(bound)}'}}"]
    for case, (named, _) in cases.items():
        lines.append(f"try{{Assert-BuilderInterpreter ([ordered]@{{builder_python='{ps(named)}'}}) $runtime;$r['{case}']=''}}catch{{$r['{case}']=$_.Exception.Message}}")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    for case, (_, expected) in cases.items():
        assert (value[case] == '') if expected is None else (expected in value[case]), (case, value[case])


def test_decision_and_candidate_are_read_only_from_a_protected_build_directory(tmp_path):
    make_base(tmp_path)
    build = write_build(tmp_path / 'build', CONTRACT, make_decision(CONTRACT))
    value = run(tmp_path, f'''
      $r=[ordered]@{{}}
      $script:calls.Clear();$d=Read-StagingDecision '{ps(build)}';$c=Read-StagingCandidate '{ps(build)}' $d;$r['calls']=@($script:calls)
      $script:unprotected['{ps(build / 'decision.json')}']=$true
      try{{$null=Read-StagingDecision '{ps(build)}';$r['decision']=''}}catch{{$r['decision']=$_.Exception.Message}}
      $script:unprotected=@{{}};$script:unprotected['{ps(build / 'pipeline.json')}']=$true
      try{{$null=Read-StagingCandidate '{ps(build)}' $d;$r['candidate']=''}}catch{{$r['candidate']=$_.Exception.Message}}
      $r|ConvertTo-Json -Compress''')
    assert value['calls'] == ['protected:' + str(build / 'decision.json'), 'protected:' + str(build / 'pipeline.json')]
    assert value['decision'].startswith('decision.json is not inside a protected build directory') and 'Untrusted protected owner' in value['decision']
    assert value['candidate'].startswith('The candidate pipeline.json is not inside a protected build directory')


# ----------------------------------------------------------------------------------------------- only-Gemini rule (mirrors retarget)

def _tier_candidates_changed(document):
    _set_contract(document)
    tiers = document['routing']['tiers']
    first = next(iter(tiers))
    tiers[first] = list(reversed(tiers[first]))


def _tier_key_order_changed(document):
    _set_contract(document)
    document['routing']['tiers'] = dict(reversed(list(document['routing']['tiers'].items())))


DIFF_CASES = {
    'held_bytes': (COMMISSIONED, 'GEMINI_HELD_COMMISSIONED_BYTES'),
    'contract': (CONTRACT, 'GEMINI_CONTRACT'),
    'contract_other_binding': (OTHER_CONTRACT, 'GEMINI_CONTRACT'),
    'contract_reformatted': (mutate(_set_contract, indent=4), 'GEMINI_CONTRACT'),
    'claude_changed': (mutate(lambda d: (_set_contract(d), d['providers']['claude'].__setitem__('model', 'claude-other'))), 'changes more than providers.gemini'),
    'claude_only_changed': (mutate(lambda d: d['providers']['claude'].__setitem__('model', 'claude-other')), 'changes more than providers.gemini'),
    'tier_candidates_changed': (mutate(_tier_candidates_changed), 'changes more than providers.gemini'),
    'tier_key_order_changed': (mutate(_tier_key_order_changed), 'changes more than providers.gemini'),
    'extra_top_key': (mutate(lambda d: (_set_contract(d), d.__setitem__('extra', 1))), 'changes more than providers.gemini'),
    'slots_changed': (mutate(lambda d: (_set_contract(d), d.__setitem__('max_execution_slots', 3))), 'changes more than providers.gemini'),
    'extra_provider': (mutate(lambda d: (_set_contract(d), d['providers'].__setitem__('other', {'executable': 'x'}))), 'changes more than providers.gemini'),
    'gemini_removed': (mutate(lambda d: d['providers'].pop('gemini')), 'no providers.gemini object'),
    'gemini_null': (mutate(lambda d: d['providers'].__setitem__('gemini', None)), 'no providers.gemini object'),
    'providers_array': (mutate(lambda d: d.__setitem__('providers', [])), 'no providers.gemini object'),
    'top_array': (b'[1]', 'no providers.gemini object'),
    'whitespace_only': (mutate(lambda d: None, indent=4), 'without a providers.gemini change'),
    'not_json': (b'{not json', 'is not JSON'),
}


@pytest.fixture(scope='module')
def diff_results(tmp_path_factory):
    folder = tmp_path_factory.mktemp('diff')
    base = make_base(folder)
    commissioned = base / R4_DIR / 'pipeline.json'
    paths = {}
    for case, (data, _) in DIFF_CASES.items():
        target = folder / 'cases' / case / TARGET_DIR / 'pipeline.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(data)
        # retarget-warden-r5 (audit C-F8) also wants the stager's receipt for exactly these bytes beside them.
        (target.parent / RECEIPT_NAME).write_text(json.dumps({'schema': 'cochem-config-only-staging/2', 'status': 'STAGED', 'staged_path': str(target),
                                                               'staged_sha256': sha(data)}), encoding='ascii')
        paths[case] = target
    stager = ['$r=[ordered]@{};$reference=Read-R3Text (Read-R3Control $script:commissionedPath $script:configPin)']
    for case, path in paths.items():
        stager.append(f"$c=Read-R3Control '{ps(path)}';try{{$m=Assert-OnlyGeminiChanges (Read-R3Text $c) $c.Sha256 $reference;$r['{case}']=[ordered]@{{refused=$false;mode=$m}}}}"
                      f"catch{{$r['{case}']=[ordered]@{{refused=$true;message=$_.Exception.Message}}}}")
    stager.append('$r|ConvertTo-Json -Compress -Depth 4')
    mine = run(folder, '\n'.join(stager), base=base)
    theirs = retarget_verdicts(folder, paths, commissioned, PIN)
    return {'mine': mine, 'theirs': theirs, 'paths': paths}


@pytest.mark.parametrize('case', sorted(DIFF_CASES))
def test_only_gemini_rule_matches_retarget_assert_r5_config(diff_results, case):
    mine, theirs = diff_results['mine'][case], diff_results['theirs']['results'][case]
    expected = DIFF_CASES[case][1]
    if expected.startswith('GEMINI_'):
        assert mine == {'refused': False, 'mode': expected}, mine
        assert theirs['refused'] is False and theirs['mode'] == expected and theirs['sha'] == sha256_file(diff_results['paths'][case]), theirs
    else:
        assert mine['refused'] is True and expected in mine['message'], mine
        assert theirs['refused'] is True, ('retarget must refuse what the stager refuses', theirs)


RETARGET_PRELUDE = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('__RETARGET__',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($f in @($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]})){. ([scriptblock]::Create($f.Extent.Text))}
$script:Target='r5';$script:Attempt='v1';$script:scriptDirectory='__ROOT__';Set-RetargetConstants
$script:realPattern=$script:r5ConfigPattern;$script:realCommissioned=$script:r4RestoreConfig;$script:realPin=$script:configPin
$held=[Collections.Generic.List[IO.FileStream]]::new()
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){throw ('Fixture control missing: '+$Path)}
  $bytes=[IO.File]::ReadAllBytes($Path);if($bytes.Length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $sha=[Security.Cryptography.SHA256]::Create();try{$actual=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
  if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  [pscustomobject]@{Stream=[IO.MemoryStream]::new($bytes);Sha256=$actual;Length=[long]$bytes.Length}}
function Read-R3Text {param($Control)$Control.Stream.Position=0;$reader=[IO.StreamReader]::new($Control.Stream,[Text.Encoding]::UTF8,$true,4096,$true);try{$reader.ReadToEnd()}finally{$reader.Dispose()}}
'''


def retarget_verdicts(folder: Path, paths: dict, commissioned: Path, pin: str) -> dict:
    """retarget-warden-r5.ps1's own Assert-R5Config (from its AST) on the given staged paths, against the given commissioned file."""
    lines = [f"$script:r4RestoreConfig='{ps(commissioned)}';$script:configPin='{pin}'",
             r"$script:r5ConfigPattern='^.+\\WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}\\pipeline\.json$'", '$r=[ordered]@{}']
    for case, path in paths.items():
        lines.append(f"try{{$b=Assert-R5Config '{ps(path)}';$r['{case}']=[ordered]@{{refused=$false;mode=$b.mode;sha=$b.sha256;length=$b.length;path=$b.path}}}}"
                     f"catch{{$r['{case}']=[ordered]@{{refused=$true;message=$_.Exception.Message}}}}")
    lines.append(f"[ordered]@{{results=$r;real_target_matches=[bool]('{ps(REAL_TARGET)}' -cmatch $script:realPattern);real_pattern=$script:realPattern;"
                 "real_commissioned=$script:realCommissioned;real_pin=$script:realPin}|ConvertTo-Json -Compress -Depth 5")
    return run(folder, '\n'.join(lines), prelude=RETARGET_PRELUDE)


def test_retarget_real_constants_accept_the_real_target_and_name_the_same_commissioned_file(diff_results):
    theirs = diff_results['theirs']
    assert theirs['real_target_matches'] is True and theirs['real_commissioned'] == str(REAL_COMMISSIONED) and theirs['real_pin'] == CONFIG_PIN


# ----------------------------------------------------------------------------------------------- r5 runtime and parser

PARSER_CASES = {'ok': ('0', PARSER_OK, None),
                'five_workers': ('0', '{"parser_valid":true,"worker_identities":5,"max_shared_slots":4,"knowledge_enabled":true}', 'six worker identities'),
                'three_slots': ('0', '{"parser_valid":true,"worker_identities":6,"max_shared_slots":3,"knowledge_enabled":true}', 'six worker identities'),
                'knowledge_off': ('0', '{"parser_valid":true,"worker_identities":6,"max_shared_slots":4,"knowledge_enabled":false}', 'six worker identities'),
                'valid_string': ('0', '{"parser_valid":"true","worker_identities":6,"max_shared_slots":4,"knowledge_enabled":true}', 'six worker identities'),
                'slots_string': ('0', '{"parser_valid":true,"worker_identities":6,"max_shared_slots":"4","knowledge_enabled":true}', 'six worker identities'),
                'exit_1': ('1', '', 'parser failed (exit 1)'), 'not_json': ('0', 'Traceback', 'printed no JSON')}


def test_parser_runs_the_r5_interpreter_with_single_quoted_python_and_judges_counts(tmp_path):
    make_base(tmp_path)
    lines = ['$r=[ordered]@{}']
    for case, (code, stdout, _) in PARSER_CASES.items():
        lines.append(f"$script:parserCode={code};$script:parserStdout='{ps(stdout)}'")
        lines.append(f"try{{$null=Invoke-R5ConfigParser 'C:\\r5\\python.exe' 'C:\\build\\pipeline.json';$r['{case}']=''}}catch{{$r['{case}']=$_.Exception.Message}}")
    lines.append("$first=@($script:nativeCalls[0]);$r['exe']=$first[0];$r['args']=@($first[1..5]+$first[7]);$r['code_has_double_quote']=$first[6].Contains([string][char]34);$r['code']=$first[6]")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    for case, (_, _, expected) in PARSER_CASES.items():
        assert (value[case] == '') if expected is None else (expected in value[case]), (case, value[case])
    assert value['exe'] == 'C:\\r5\\python.exe' and value['args'] == ['-I', '-B', '-X', 'utf8', '-c', 'C:\\build\\pipeline.json']
    assert value['code_has_double_quote'] is False and 'from cochem_pipeline.config import load_config' in value['code']


RUNTIME_CASES = {'ok': None, 'none': 'found 0', 'two': 'found 2', 'decoys_only': 'found 0', 'wrong_target_root': 'not a successful stopped-runtime build',
                 'wrong_mode': 'not a successful stopped-runtime build', 'wrong_schema': 'not a successful stopped-runtime build',
                 'bad_venv_sha': 'not a successful stopped-runtime build', 'python_mismatch': 'Source digest changed', 'not_json': 'is not JSON',
                 'missing_after': 'Fixture control missing'}


def test_r5_runtime_is_the_single_installed_root_bound_to_its_install_receipt(tmp_path):
    bases = {}
    for case in RUNTIME_CASES:
        base = tmp_path / 'runtime' / case
        base.mkdir(parents=True)
        bases[case] = base
        if case == 'ok':
            make_r5(base)
        elif case == 'two':
            make_r5(base)
            make_r5(base, name='Pipeline4.2.7-windows-20261012-r5')
        elif case == 'decoys_only':
            make_r5(base, name='Pipeline4.2.7-windows-20261011-r5-old')
            make_r5(base, name='Pipeline4.2.7-windows-20261011-R5')
        elif case == 'wrong_target_root':
            make_r5(base, after={'target_root': 'C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261009-r4'})
        elif case == 'wrong_mode':
            make_r5(base, after={'mode': 'HELD'})
        elif case == 'wrong_schema':
            make_r5(base, after={'schema': 'cochem-stopped-runtime-update/2'})
        elif case == 'bad_venv_sha':
            make_r5(base, after={'runtime_bindings': {'venv_python_sha256': 'XYZ'}})
        elif case == 'python_mismatch':
            make_r5(base, after={'runtime_bindings': {'venv_python_sha256': sha(b'another interpreter')}})
        elif case == 'not_json':
            make_r5(base, raw_after=b'{')
        elif case == 'missing_after':
            make_r5(base, after={'__absent__': True})
    make_base(tmp_path)
    lines = ['$r=[ordered]@{}']
    for case, base in bases.items():
        lines.append(f"$script:base='{ps(base)}';try{{$x=Get-R5ParserRuntime;$r['{case}']=[ordered]@{{ok=$true;root=$x.root;python=$x.python;python_sha=$x.python_sha256;after=$x.install_after_sha256}}}}"
                     f"catch{{$r['{case}']=[ordered]@{{ok=$false;message=$_.Exception.Message}}}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    value = run(tmp_path, '\n'.join(lines))
    for case, expected in RUNTIME_CASES.items():
        got = value[case]
        if expected is None:
            root = bases[case] / R5_DIR
            assert got == {'ok': True, 'root': str(root), 'python': str(root / '.venv' / 'Scripts' / 'python.exe'),
                           'python_sha': sha256_file(root / '.venv' / 'Scripts' / 'python.exe'), 'after': sha256_file(root / 'install-after.json')}, got
        else:
            assert got['ok'] is False and expected in got['message'], (case, got)


# ----------------------------------------------------------------------------------------------- target

def test_target_path_rule_is_retargets_pattern_and_never_the_commissioned_file(tmp_path):
    make_base(tmp_path)
    real_cases = {'real_v1': REAL_TARGET, 'v12': REAL_TARGET.replace('-r5-v1', '-r5-v12'), 'other_date': REAL_TARGET.replace('20261011', '20261012'),
                  'upper_r5': REAL_TARGET.replace('-r5-', '-R5-'), 'r4_name': REAL_TARGET.replace('-r5-', '-r4-'),
                  'other_file': REAL_TARGET.replace('pipeline.json', 'pipeline.staged.json'), 'commissioned': str(REAL_COMMISSIONED),
                  'other_drive': 'D' + REAL_TARGET[1:], 'v1000': REAL_TARGET.replace('-r5-v1', '-r5-v1000'), 'lower_drive': 'c' + REAL_TARGET[1:]}
    lines = ['$r=[ordered]@{};& $script:real[\'Set-StagerConstants\']']
    for case, path in real_cases.items():
        lines.append(f"try{{Assert-StagingTargetPath '{ps(path)}';$r['{case}']=''}}catch{{$r['{case}']=$_.Exception.Message}}")
    lines.append(r"$script:r5ConfigPattern='^.+\\pipeline\.json$'")
    loose = {'equal_commissioned': '$script:commissionedPath', 'equal_commissioning_copy': '$script:commissioningCopyPath',
             'equal_commissioned_upper': "$script:commissionedPath.Replace('Program Files','PROGRAM FILES').Replace('CoChem','COCHEM')",
             'inside_root': "(Join-Path $script:commissionedRoot 'WardenConfig4.2.7-windows-20261011-r5-v1\\pipeline.json')",
             'dotdot': "'C:\\Program Files\\CoChem\\x\\..\\WardenConfig4.2.7-windows-20261011-r5-v1\\pipeline.json'"}
    for case, expression in loose.items():
        lines.append(f"try{{Assert-StagingTargetPath {expression};$r['{case}']=''}}catch{{$r['{case}']=$_.Exception.Message}}")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    for case in ('real_v1', 'v12', 'other_date'):
        assert value[case] == '', (case, value[case])
    for case in ('upper_r5', 'r4_name', 'other_file', 'commissioned', 'other_drive', 'v1000', 'lower_drive'):
        assert 'The staging target must be C:\\Program Files\\CoChem\\WardenConfig4.2.7-windows-<date>-r5-vN\\pipeline.json' in value[case], case
    for case in ('equal_commissioned', 'equal_commissioning_copy', 'equal_commissioned_upper'):
        assert 'is the commissioned configuration, which is never overwritten' in value[case], case
    assert 'lies inside the commissioned runtime root' in value['inside_root'] and 'is not a normalized path' in value['dotdot']


RECEIPT_NAME = 'staging-receipt-20261011T101010Z-' + '0123456789abcdef' * 2 + '.json'
HELD_NAME = 'staging-held-20261011T101010Z-' + 'fedcba9876543210' * 2 + '.json'
STATE_CASES = {'absent': None, 'identical': None, 'identical_without_receipts': None, 'different': 'A different pipeline.json is already staged at',
               'no_config': 'exists without pipeline.json', 'only_receipt': 'exists without pipeline.json', 'extra_file': 'unexpected entries',
               'held_record': 'unexpected entries', 'subdirectory': 'unexpected entries', 'bad_receipt_name': 'unexpected entries',
               'wrong_acl_directory': 'does not carry ' + SDDL, 'wrong_acl_file': 'does not carry ' + SDDL, 'wrong_acl_receipt': 'does not carry ' + SDDL,
               'root_is_file': 'exists and is not a directory', 'too_large': 'Bounded r3 control length differs.'}


def test_pre_existing_target_is_accepted_only_when_byte_identical_protected_and_clean(tmp_path):
    make_base(tmp_path)
    roots = {}
    for case in STATE_CASES:
        root = tmp_path / 'states' / case / TARGET_DIR
        root.parent.mkdir(parents=True)
        roots[case] = root
        if case == 'absent':
            continue
        if case == 'root_is_file':
            root.write_bytes(CONTRACT)
            continue
        root.mkdir()
        if case not in ('no_config', 'only_receipt'):
            (root / 'pipeline.json').write_bytes({'different': OTHER_CONTRACT, 'too_large': b'{' + b' ' * 1048576 + b'}'}.get(case, CONTRACT))
        if case not in ('identical_without_receipts', 'no_config'):
            (root / RECEIPT_NAME).write_text('{}', encoding='ascii')
        extra = {'extra_file': 'notes.txt', 'held_record': HELD_NAME, 'bad_receipt_name': 'staging-receipt-1.json'}.get(case)
        if extra:
            (root / extra).write_text('{}', encoding='ascii')
        if case == 'subdirectory':
            (root / 'old').mkdir()
    lines = ['$r=[ordered]@{}']
    for case, root in roots.items():
        setup = ''
        if case == 'wrong_acl_directory':
            setup = f"$script:badAcl['{ps(root)}']=$script:wrongAcl;"
        elif case == 'wrong_acl_file':
            setup = f"$script:badAcl['{ps(root / 'pipeline.json')}']=$script:wrongAcl;"
        elif case == 'wrong_acl_receipt':
            setup = f"$script:badAcl['{ps(root / RECEIPT_NAME)}']=$script:wrongAcl;"
        lines.append(f"$script:badAcl=@{{}};{setup}$script:calls.Clear();try{{$s=Get-StagingTargetState '{ps(root)}' '{ps(root / 'pipeline.json')}' '{sha(CONTRACT)}' {len(CONTRACT)};"
                     f"$r['{case}']=[ordered]@{{ok=$true;state=$s.state;receipts=@($s.existing_receipts);sha=$s.existing_sha256;calls=@($script:calls)}}}}"
                     f"catch{{$r['{case}']=[ordered]@{{ok=$false;message=$_.Exception.Message}}}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    value = run(tmp_path, '\n'.join(lines))
    for case, expected in STATE_CASES.items():
        got = value[case]
        if expected is None:
            assert got['ok'] is True, (case, got)
        else:
            assert got['ok'] is False and expected in got['message'], (case, got)
    assert value['absent']['state'] == 'ABSENT' and value['absent']['calls'] == ['protected:' + str(roots['absent'].parent)]
    assert value['identical']['state'] == 'ALREADY_STAGED_IDENTICAL' and value['identical']['receipts'] == [RECEIPT_NAME] and value['identical']['sha'] == sha(CONTRACT)
    assert value['identical_without_receipts']['state'] == 'ALREADY_STAGED_IDENTICAL' and value['identical_without_receipts']['receipts'] == []
    acl_calls = [c for c in value['identical']['calls'] if c.startswith('acl:')]
    assert acl_calls == ['acl:' + str(roots['identical']), 'acl:' + str(roots['identical'] / 'pipeline.json'), 'acl:' + str(roots['identical'] / RECEIPT_NAME)]
    assert HELD_NAME in value['held_record']['message'] and 'old' in value['subdirectory']['message']
    assert sha256_file(roots['different'] / 'pipeline.json') == sha(OTHER_CONTRACT), 'a different staged file is never touched'


ACL_CASES = {'good': '$script:goodAcl',
             'owner_system': "[pscustomobject]@{owner='S-1-5-18';protected=$true;rules=$script:goodAcl.rules}",
             'owner_user': "[pscustomobject]@{owner='S-1-5-21-1-2-3-1001';protected=$true;rules=$script:goodAcl.rules}",
             'unprotected': "[pscustomobject]@{owner='S-1-5-32-544';protected=$false;rules=$script:goodAcl.rules}",
             'users_read': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@($script:goodAcl.rules)+@(New-AclRule 'S-1-5-32-545' 'Allow' 1179817)}",
             'only_system': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@((New-AclRule 'S-1-5-18'),(New-AclRule 'S-1-5-18'))}",
             'system_and_user': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@((New-AclRule 'S-1-5-18'),(New-AclRule 'S-1-5-21-1-2-3-1001'))}",
             'deny': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@((New-AclRule 'S-1-5-18'),(New-AclRule 'S-1-5-32-544' 'Deny'))}",
             'inherited': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@((New-AclRule 'S-1-5-18'),(New-AclRule 'S-1-5-32-544' 'Allow' 2032127 $true))}",
             'read_only': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@((New-AclRule 'S-1-5-18'),(New-AclRule 'S-1-5-32-544' 'Allow' 1179817))}",
             'oici': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@((New-AclRule 'S-1-5-18' 'Allow' 2032127 $false 'ContainerInherit, ObjectInherit'),(New-AclRule 'S-1-5-32-544'))}",
             'empty': "[pscustomobject]@{owner='S-1-5-32-544';protected=$true;rules=@()}"}


def test_acl_rule_is_exactly_owner_ba_protected_system_and_administrators_full_control(tmp_path):
    make_base(tmp_path)
    probe = tmp_path / 'acl-probe'
    lines = ['$r=[ordered]@{}']
    for case, expression in ACL_CASES.items():
        lines.append(f"$r['{case}']=Test-StagingAcl ({expression})")
    lines.append(f"$sec=[Security.AccessControl.DirectorySecurity]::new();$sec.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;'+$script:userSid+')')")
    lines.append(f"[IO.DirectoryInfo]::new('{ps(probe)}').Create($sec);$s=& $script:real['Get-StagingAclSummary'] '{ps(probe)}'")
    lines.append("$r['real']=[ordered]@{owner=$s.owner;user=$script:userSid;protected=$s.protected;count=@($s.rules).Count;sids=@($s.rules|ForEach-Object {$_.sid});"
                 "rights=@($s.rules|ForEach-Object {$_.rights});inheritance=@($s.rules|ForEach-Object {$_.inheritance});verdict=(Test-StagingAcl $s)}")
    lines.append(f"try{{& $script:real['Get-StagingAclSummary'] '{ps(tmp_path / 'missing-dir')}';$r['missing']='read'}}catch{{$r['missing']='refused'}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    value = run(tmp_path, '\n'.join(lines))
    assert value['good'] == ''
    for case in ACL_CASES:
        if case != 'good':
            assert value[case], case
    assert 'owner is S-1-5-18' in value['owner_system'] and 'not protected' in value['unprotected'] and 'found 3' in value['users_read']
    assert 'not exactly SYSTEM and Administrators' in value['only_system'] and 'not exactly SYSTEM and Administrators' in value['system_and_user']
    for case in ('deny', 'inherited', 'read_only', 'oici'):
        assert 'unexpected access rule' in value[case], case
    real = value['real']
    assert real['protected'] is True and real['count'] == 3 and set(real['sids']) == {'S-1-5-18', 'S-1-5-32-544', real['user']}
    assert set(real['rights']) == {2032127} and set(real['inheritance']) == {'ContainerInherit, ObjectInherit'} and real['verdict'] != ''
    assert value['missing'] == 'refused'


# ----------------------------------------------------------------------------------------------- the main function (all seams stubbed)

def _check_status(value, status, code):
    assert value['objects'] == 1 and value['line_count'] == 2 and value['exit_code'] == code, value
    line = value['status']
    assert list(line) == STATUS_KEYS and line['status'] == status and line['exit_code'] == code, line
    assert '\n' not in value['status_line'] and '\r' not in value['status_line']
    return line


def test_main_plan_with_the_held_outcome_checks_everything_and_writes_nothing(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build-held', COMMISSIONED, make_decision(COMMISSIONED, mode='held'), base=base)
    before = snapshot(tmp_path)
    value = run_main(tmp_path, f"@{{BuildDirectory='{ps(build)}'}}")
    after = snapshot(tmp_path)
    line = _check_status(value, 'PLAN_OK', 0)
    target = base / TARGET_DIR / 'pipeline.json'
    assert line == {'status': 'PLAN_OK', 'staged_path': str(target), 'staged_sha256': PIN, 'outcome': 'GEMINI_HELD_COMMISSIONED_BYTES', 'mode': 'held',
                    'receipt_path': None, 'target_state': 'ABSENT', 'exit_code': 0, 'reason': None}
    plan = value['document']
    assert plan['schema'] == 'cochem-config-only-staging-plan/2' and plan['mode'] == 'READ_ONLY_PLAN' and plan['files_written'] == 0 and plan['tasks_changed'] == 0
    assert plan['decision']['sha256'] == sha256_file(build / 'decision.json') and plan['candidate']['sha256'] == PIN and plan['commissioned']['sha256'] == PIN
    assert plan['diff'] == {'outcome_by_content': 'GEMINI_HELD_COMMISSIONED_BYTES', 'only_policy_change': 'none: the commissioned bytes, Gemini held by integration_hold'}
    assert plan['parser'] == json.loads(PARSER_OK) and plan['target']['state'] == 'ABSENT' and plan['staging_sddl'] == SDDL and plan['script_sha256'] == sha256_file(SCRIPT)
    assert plan['r5_runtime']['python'] == str(base / R5_DIR / '.venv' / 'Scripts' / 'python.exe')
    assert plan['decision']['builder_python'] == str(r5_python(base)) and plan['decision']['builder_script_sha256'] == BUILDER_SHA
    assert 'protected:' + str(build / 'decision.json') in value['calls'] and 'protected:' + str(build / 'pipeline.json') in value['calls']
    assert value['native'] == [[str(base / R5_DIR / '.venv' / 'Scripts' / 'python.exe'), '-I', '-B', '-X', 'utf8', '-c', value['native'][0][6], str(build / 'pipeline.json')]]
    assert before == after, 'plan mode writes nothing'
    assert value['calls'][:3] == ['host', 'constants', 'helpers'] and not any(c.startswith('security:') for c in value['calls'])


def test_main_plan_with_the_contract_outcome_reports_the_gemini_change(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build-contract', CONTRACT, make_decision(CONTRACT), base=base)
    value = run_main(tmp_path, f"@{{BuildDirectory='{ps(build)}'}}")
    line = _check_status(value, 'PLAN_OK', 0)
    assert line['outcome'] == 'GEMINI_CONTRACT' and line['mode'] == 'attempt' and line['staged_sha256'] == sha(CONTRACT)
    assert line['staged_path'] == str(base / TARGET_DIR / 'pipeline.json') and line['target_state'] == 'ABSENT'
    plan = value['document']
    assert plan['diff']['only_policy_change'] == 'providers.gemini contract' and plan['decision']['gates_passed'] == 6 and plan['decision']['chosen_bindings_count'] == 1
    assert listing(base) == sorted([R4_DIR, R5_DIR])


def test_main_apply_stages_the_held_bytes_then_a_rerun_records_already_staged_identical(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build-held', COMMISSIONED, make_decision(COMMISSIONED), base=base)
    build_before = snapshot(build)
    arguments = f"@{{BuildDirectory='{ps(build)}';Apply=$true}}"
    value = run(tmp_path, "$script:fixtureAdmin=$true;$r=[ordered]@{};$r['first']=Invoke-Main " + arguments + ";$r['second']=Invoke-Main " + arguments +
                ";$r['plan']=Invoke-Main @{BuildDirectory='" + ps(build) + "'};$r|ConvertTo-Json -Compress -Depth 14")
    root = base / TARGET_DIR
    target = root / 'pipeline.json'
    first, second, plan = value['first'], value['second'], value['plan']
    for item in (first, second, plan):
        item['status'] = json.loads(item['status_line'])
    line = _check_status(first, 'STAGED', 0)
    assert line['staged_path'] == str(target) and line['staged_sha256'] == PIN and line['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and line['mode'] == 'attempt'
    assert line['target_state'] == 'ABSENT' and RECEIPT_RE.match(Path(line['receipt_path']).name) and Path(line['receipt_path']).parent == root
    assert target.read_bytes() == COMMISSIONED
    assert [c for c in first['calls'] if c.startswith('security:')] == ['security:True', 'security:False', 'security:False']
    assert 'protected:' + str(base) in first['calls'] and 'r3:' + str(target) in first['calls']
    line2 = _check_status(second, 'ALREADY_STAGED_IDENTICAL', 0)
    assert line2['staged_path'] == str(target) and line2['staged_sha256'] == PIN and line2['target_state'] == 'ALREADY_STAGED_IDENTICAL'
    assert line2['receipt_path'] != line['receipt_path'] and [c for c in second['calls'] if c.startswith('security:')] == ['security:False']
    line3 = _check_status(plan, 'PLAN_OK', 0)
    assert line3['target_state'] == 'ALREADY_STAGED_IDENTICAL' and plan['document']['apply_would'].startswith('write one ALREADY_STAGED_IDENTICAL receipt')
    names = listing(root)
    receipts = [n for n in names if RECEIPT_RE.match(n)]
    assert names == sorted(['pipeline.json'] + receipts) and len(receipts) == 2
    receipt1 = json.loads(Path(line['receipt_path']).read_text(encoding='utf-8'))
    receipt2 = json.loads(Path(line2['receipt_path']).read_text(encoding='utf-8'))
    assert first['document']['receipt_sha256'] == sha256_file(line['receipt_path']) and second['document']['receipt_sha256'] == sha256_file(line2['receipt_path'])
    assert first['document']['schema'] == 'cochem-config-only-staging-result/2' and first['document']['retarget_config_argument'] == str(target)
    for receipt, status in ((receipt1, 'STAGED'), (receipt2, 'ALREADY_STAGED_IDENTICAL')):
        assert receipt['schema'] == 'cochem-config-only-staging/2' and receipt['status'] == status
        assert receipt['staged_path'] == str(target) and receipt['staged_sha256'] == PIN and receipt['staged_length'] == len(COMMISSIONED)
        assert receipt['decision_path'] == str(build / 'decision.json') and receipt['decision_sha256'] == sha256_file(build / 'decision.json')
        assert receipt['candidate_sha256'] == PIN and receipt['commissioned_path'] == str(base / R4_DIR / 'pipeline.json') and receipt['commissioned_sha256'] == PIN
        assert receipt['decision_commissioned_path'] == str(REAL_COMMISSIONED) and receipt['mode'] == 'attempt' and receipt['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES'
        assert list(receipt['gates']) == ['G1', 'G2', 'G3', 'G4', 'G5', 'G6'] and receipt['gates']['G1']['pass'] is False and receipt['gates_passed'] == 0
        assert receipt['parser'] == json.loads(PARSER_OK) and receipt['script_sha256'] == sha256_file(SCRIPT) and receipt['staging_sddl'] == SDDL
        assert receipt['acl_verified'] is True and receipt['retarget_config_argument'] == str(target) and receipt['tasks_changed'] == 0
        assert receipt['commissioned_file_modified'] is False and receipt['automatic_retry_allowed'] is False and receipt['operator'] == 'AETHERDESK\\ansac'
        assert receipt['r5_runtime']['python_sha256'] == sha256_file(base / R5_DIR / '.venv' / 'Scripts' / 'python.exe')
        assert receipt['only_policy_change'].startswith('none: the commissioned bytes') and receipt['staged_utc'].endswith('Z')
        assert receipt['builder'] == {'python': str(r5_python(base)), 'script_sha256': BUILDER_SHA, 'isolated_mode': True, 'interpreter_is_bound_r5': True}
    assert receipt1['previous_receipts'] == [] and receipt2['previous_receipts'] == [Path(line['receipt_path']).name]
    assert snapshot(build) == build_before and sha256_file(base / R4_DIR / 'pipeline.json') == PIN
    handoff = retarget_verdicts(tmp_path, {'staged': target}, base / R4_DIR / 'pipeline.json', PIN)
    assert handoff['results']['staged'] == {'refused': False, 'mode': 'GEMINI_HELD_COMMISSIONED_BYTES', 'sha': PIN, 'length': len(COMMISSIONED), 'path': str(target)}


def test_main_apply_stages_the_contract_and_retarget_binds_it_as_gemini_contract(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build-contract', CONTRACT, make_decision(CONTRACT), base=base)
    value = run_main(tmp_path, f"@{{BuildDirectory='{ps(build)}';Apply=$true;Attempt='v3'}}", setup='$script:fixtureAdmin=$true;')
    line = _check_status(value, 'STAGED', 0)
    root = base / TARGET_DIR.replace('-v1', '-v3')
    target = root / 'pipeline.json'
    assert line['staged_path'] == str(target) and line['staged_sha256'] == sha(CONTRACT) and line['outcome'] == 'GEMINI_CONTRACT' and line['mode'] == 'attempt'
    assert target.read_bytes() == CONTRACT
    receipt = json.loads(Path(line['receipt_path']).read_text(encoding='utf-8'))
    assert receipt['only_policy_change'] == 'providers.gemini contract' and receipt['gates_passed'] == 6 and receipt['chosen_bindings'] == {'gemini-3.8-flash': 'gemini-3.8-flash-high'}
    assert receipt['effort_contracts'] == {} and receipt['decision_error'] is None and receipt['candidate_length'] == len(CONTRACT)
    handoff = retarget_verdicts(tmp_path, {'staged': target}, base / R4_DIR / 'pipeline.json', PIN)
    assert handoff['results']['staged'] == {'refused': False, 'mode': 'GEMINI_CONTRACT', 'sha': sha(CONTRACT), 'length': len(CONTRACT), 'path': str(target)}
    assert handoff['real_target_matches'] is True


def test_main_refuses_a_non_owner_apply_before_reading_anything(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build', COMMISSIONED, make_decision(COMMISSIONED), base=base)
    for setup in ('$script:fixtureAdmin=$false;', "$script:fixtureAdmin=$true;$script:fixtureUser='AETHERDESK\\other';"):
        value = run_main(tmp_path, f"@{{BuildDirectory='{ps(build)}';Apply=$true}}", setup=setup)
        line = _check_status(value, 'HELD', 4)
        assert 'requires the owner in Administrator Windows PowerShell' in line['reason'] and value['calls'] == ['host']
        assert value['document']['phase'] == 'IDENTITY' and value['document']['changed'] is False and value['document']['target_path'] is None
    assert not (base / TARGET_DIR).exists()


MAIN_REFUSALS = {
    # case: (candidate, decision, setup, exit code, phase, reason fragment)
    'decision_missing': (COMMISSIONED, None, '', 10, 'DECISION', 'decision.json is missing'),
    'candidate_sha': (CONTRACT, make_decision(CONTRACT, candidate_sha256='0' * 64), '', 11, 'CANDIDATE', 'differs from decision.json candidate_sha256'),
    'commissioned_pin': (CONTRACT, make_decision(CONTRACT, commissioned_sha256='1' * 64), '', 12, 'COMMISSIONED', 'is not the commissioned pin'),
    'outcome_gate': (CONTRACT, make_decision(CONTRACT, gates=_gates(G4={'pass': False, 'reason': 'six-slot staging failed'})), '', 13, 'OUTCOME', 'failed: G4.'),
    'diff_non_gemini': (DIFF_CASES['claude_changed'][0], make_decision(DIFF_CASES['claude_changed'][0]), '', 14, 'DIFF', 'changes more than providers.gemini'),
    'diff_no_gemini_change': (DIFF_CASES['whitespace_only'][0], make_decision(DIFF_CASES['whitespace_only'][0]), '', 14, 'DIFF', 'without a providers.gemini change'),
    'parser_counts': (CONTRACT, make_decision(CONTRACT), "$script:parserStdout='{\"parser_valid\":true,\"worker_identities\":5,\"max_shared_slots\":4,\"knowledge_enabled\":true}';",
                      15, 'PARSER', 'six worker identities'),
    'parser_exit': (CONTRACT, make_decision(CONTRACT), '$script:parserCode=1;', 15, 'PARSER', 'parser failed (exit 1)'),
    'runtime_missing': (CONTRACT, make_decision(CONTRACT), '__NO_R5__', 15, 'PARSER', 'found 0'),
    # Deploy audit B-F2: protected build directory, builder provenance and bindings that match the candidate.
    'decision_unprotected': (CONTRACT, make_decision(CONTRACT), "$script:unprotected['__BUILD__\\decision.json']=$true;", 10, 'DECISION',
                             'decision.json is not inside a protected build directory'),
    'candidate_unprotected': (CONTRACT, make_decision(CONTRACT), "$script:unprotected['__BUILD__\\pipeline.json']=$true;", 11, 'CANDIDATE',
                              'The candidate pipeline.json is not inside a protected build directory'),
    'audit_repro_forged_builder': (CONTRACT, FORGED_DECISION, '', 10, 'DECISION', 'builder.isolated_mode must be true'),
    'builder_sha_other': (CONTRACT, make_decision(CONTRACT, builder=builder_block(script_sha256='0' * 64)), '', 10, 'DECISION', 'is not the pinned builder'),
    'builder_python_other': (CONTRACT, make_decision(CONTRACT, builder=builder_block(python='C:\\Python314\\python.exe')), '', 10, 'PROVENANCE',
                             'decision.json builder.python C:\\Python314\\python.exe is not the bound r5 interpreter'),
    'builder_python_other_held': (COMMISSIONED, make_decision(COMMISSIONED, builder=builder_block(python='C:\\Python314\\python.exe')), '', 10,
                                  'PROVENANCE', 'is not the bound r5 interpreter'),
    'bindings_differ': (CONTRACT, make_decision(CONTRACT, chosen_bindings={'gemini-3.8-flash': 'gemini-3.8-flash-low'}), '', 13, 'OUTCOME',
                        'chosen_bindings differs from the candidate providers.gemini.model_bindings'),
    'bindings_extra_route': (CONTRACT, make_decision(CONTRACT, chosen_bindings={'gemini-3.8-flash': 'gemini-3.8-flash-high',
                                                                               'gemini-3.8-flash:extended': {'argv': 'gemini-3.8-flash', 'reports': 'gemini-3.8-flash-high'}}),
                             '', 13, 'OUTCOME', 'chosen_bindings differs from the candidate'),
}


@pytest.mark.parametrize('apply', [False, True])
def test_main_refusals_carry_their_exit_code_and_change_nothing(tmp_path, apply):
    base = make_base(tmp_path)
    no_r5 = make_base(tmp_path, name='CoChemNoR5', r5=False)
    lines = ['$script:fixtureAdmin=$true;$r=[ordered]@{}']
    for case, (candidate, decision, setup, _, _, _) in MAIN_REFUSALS.items():
        build = write_build(tmp_path / 'builds' / case, candidate, decision, base=base)
        prefix = (f"$script:fixtureBase='{ps(no_r5 if setup == '__NO_R5__' else base)}';$script:parserCode=0;$script:parserStdout='{ps(PARSER_OK)}';"
                  "$script:unprotected=@{};")
        prefix += '' if setup == '__NO_R5__' else setup.replace('__BUILD__', ps(build))
        lines.append(f"{prefix}$r['{case}']=Invoke-Main @{{BuildDirectory='{ps(build)}';Apply=${'true' if apply else 'false'}}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 14')
    before = snapshot(tmp_path)
    value = run(tmp_path, '\n'.join(lines))
    for case, (_, _, _, code, phase, fragment) in MAIN_REFUSALS.items():
        got = value[case]
        got['status'] = json.loads(got['status_line'])
        line = _check_status(got, 'HELD', code)
        assert fragment in line['reason'] and got['document']['phase'] == phase and got['document']['changed'] is False, (case, got['document'])
        assert line['staged_path'] is None and line['receipt_path'] is None and got['document']['automatic_retry_allowed'] is False
        assert not any(c.startswith('security:') for c in got['calls']), case
    assert snapshot(tmp_path) == before, 'no refusal writes anything'


def test_main_apply_refuses_a_pre_existing_different_target_and_leaves_it_untouched(tmp_path):
    base = make_base(tmp_path)
    root = base / TARGET_DIR
    root.mkdir()
    (root / 'pipeline.json').write_bytes(OTHER_CONTRACT)
    build = write_build(tmp_path / 'build', CONTRACT, make_decision(CONTRACT), base=base)
    before = snapshot(root)
    value = run_main(tmp_path, f"@{{BuildDirectory='{ps(build)}';Apply=$true}}", setup='$script:fixtureAdmin=$true;')
    line = _check_status(value, 'HELD', 16)
    assert 'A different pipeline.json is already staged' in line['reason'] and value['document']['phase'] == 'TARGET'
    assert snapshot(root) == before and not any(c.startswith('native:') for c in value['calls']), 'refused before the parser and before any write'


def test_main_receipt_createnew_collision_is_held_with_a_record_and_blocks_reruns(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build', CONTRACT, make_decision(CONTRACT), base=base)
    arguments = f"@{{BuildDirectory='{ps(build)}';Apply=$true}}"
    value = run(tmp_path, "$script:fixtureAdmin=$true;$r=[ordered]@{};$r['first']=Invoke-Main " + arguments + r'''
      $script:fixedReceipt=Split-Path -Leaf ($r['first'].status_line|ConvertFrom-Json).receipt_path
      function New-StagingRecordName {param([string]$Prefix)if($Prefix -ceq 'staging-receipt'){return $script:fixedReceipt};& $script:real['New-StagingRecordName'] $Prefix}
      $r['collision']=Invoke-Main ''' + arguments + ";$r['rerun']=Invoke-Main " + arguments + ";$r|ConvertTo-Json -Compress -Depth 14")
    root = base / TARGET_DIR
    for item in value.values():
        item['status'] = json.loads(item['status_line'])
    first = _check_status(value['first'], 'STAGED', 0)
    receipt_path = Path(first['receipt_path'])
    receipt_bytes = receipt_path.read_bytes()
    line = _check_status(value['collision'], 'HELD', 21)
    assert 'ALREADY_STAGED_IDENTICAL at ' + str(root / 'pipeline.json') + ' but its receipt could not be written CreateNew' in line['reason']
    assert 'Do not retarget from this run' in line['reason'] and value['collision']['document']['changed'] is True
    held = [n for n in listing(root) if HELD_RE.match(n)]
    assert len(held) == 1 and value['collision']['document']['held_record'] == str(root / held[0])
    record = json.loads((root / held[0]).read_text(encoding='utf-8'))
    assert record['schema'] == 'cochem-config-only-staging-held/2' and record['phase'] == 'RECEIPT' and record['target_file_present'] is True
    assert record['automatic_retry_allowed'] is False and record['requires_reviewed_recovery'] is True and record['candidate_sha256'] == sha(CONTRACT)
    assert receipt_path.read_bytes() == receipt_bytes and (root / 'pipeline.json').read_bytes() == CONTRACT
    rerun = _check_status(value['rerun'], 'HELD', 16)
    assert 'unexpected entries' in rerun['reason'] and held[0] in rerun['reason']
    assert sorted(listing(root)) == sorted(['pipeline.json', receipt_path.name, held[0]])


def test_main_post_write_verification_failure_is_held_with_a_record(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build', CONTRACT, make_decision(CONTRACT), base=base)
    root = base / TARGET_DIR
    arguments = f"@{{BuildDirectory='{ps(build)}';Apply=$true}}"
    value = run(tmp_path, f"$script:fixtureAdmin=$true;$script:badAcl['{ps(root / 'pipeline.json')}']=$script:wrongAcl;$r=[ordered]@{{}};$r['apply']=Invoke-Main {arguments};"
                f"$script:badAcl=@{{}};$r['rerun']=Invoke-Main {arguments};$r|ConvertTo-Json -Compress -Depth 14")
    for item in value.values():
        item['status'] = json.loads(item['status_line'])
    line = _check_status(value['apply'], 'HELD', 20)
    assert 'The staged configuration is held' in line['reason'] and 'does not carry ' + SDDL in line['reason'] and value['apply']['document']['changed'] is True
    held = [n for n in listing(root) if HELD_RE.match(n)]
    assert len(held) == 1 and sorted(listing(root)) == sorted(['pipeline.json', held[0]]), 'no receipt for an unverified staging'
    record = json.loads((root / held[0]).read_text(encoding='utf-8'))
    assert record['phase'] == 'WRITE' and record['target_file_present'] is True
    rerun = _check_status(value['rerun'], 'HELD', 16)
    assert 'unexpected entries' in rerun['reason']


def test_main_directory_creation_failure_changes_nothing(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build', COMMISSIONED, make_decision(COMMISSIONED), base=base)
    value = run_main(tmp_path, f"@{{BuildDirectory='{ps(build)}';Apply=$true}}", setup='$script:fixtureAdmin=$true;$script:securityFails=$true;')
    line = _check_status(value, 'HELD', 20)
    assert 'could not be created' in line['reason'] and 'Nothing was changed.' in line['reason'] and value['document']['changed'] is False
    assert value['document']['held_record'] is None and not (base / TARGET_DIR).exists()


def test_main_directory_created_but_unverified_is_held_with_a_record_and_nothing_staged(tmp_path):
    base = make_base(tmp_path)
    build = write_build(tmp_path / 'build', COMMISSIONED, make_decision(COMMISSIONED), base=base)
    root = base / TARGET_DIR
    arguments = f"@{{BuildDirectory='{ps(build)}';Apply=$true}}"
    value = run(tmp_path, f"$script:fixtureAdmin=$true;$script:badAcl['{ps(root)}']=$script:wrongAcl;$r=[ordered]@{{}};$r['apply']=Invoke-Main {arguments};"
                f"$script:badAcl=@{{}};$r['rerun']=Invoke-Main {arguments};$r|ConvertTo-Json -Compress -Depth 14")
    for item in value.values():
        item['status'] = json.loads(item['status_line'])
    line = _check_status(value['apply'], 'HELD', 20)
    assert 'exists but could not be secured' in line['reason'] and 'Nothing was staged' in line['reason'] and value['apply']['document']['changed'] is True
    held = [n for n in listing(root) if HELD_RE.match(n)]
    assert listing(root) == held and len(held) == 1, 'no pipeline.json and no receipt in an unverified directory'
    record = json.loads((root / held[0]).read_text(encoding='utf-8'))
    assert record['phase'] == 'DIRECTORY' and record['target_file_present'] is False and value['apply']['document']['held_record'] == str(root / held[0])
    rerun = _check_status(value['rerun'], 'HELD', 16)
    assert 'unexpected entries' in rerun['reason']


def test_entry_prints_the_lines_last_the_status_line_and_returns_the_exit_code(tmp_path):
    make_base(tmp_path)
    case = tmp_path / 'entry.ps1'
    text = PRELUDE.replace('__SCRIPT__', ps(SCRIPT)).replace('__ROOT__', ps(ROOT)).replace('__BASE__', ps(tmp_path / 'CoChem')).replace('__PIN__', PIN)
    text = text.replace('__PARSER_OK__', ps(PARSER_OK)) + r'''
      function Invoke-StagePipelineConfigR5Main {param($Arguments,$ScriptPath,$ScriptDirectory)[pscustomobject]@{exit_code=13;lines=@('{"doc":1}','{"status":"HELD","exit_code":13}')}}
      $first=Invoke-StagePipelineConfigR5Entry -Arguments @{} -ScriptPath '' -ScriptDirectory ''
      function Invoke-StagePipelineConfigR5Main {param($Arguments,$ScriptPath,$ScriptDirectory)throw 'boom'}
      $second=Invoke-StagePipelineConfigR5Entry -Arguments @{} -ScriptPath '' -ScriptDirectory ''
      [Console]::Out.WriteLine(([ordered]@{first=$first;second=$second}|ConvertTo-Json -Compress))
    '''
    case.write_text(text, encoding='utf-8-sig')
    result = _powershell(case, 120)
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert json.loads(lines[-1]) == {'first': 13, 'second': 30}
    assert lines[-4:-1][0] == '{"doc":1}' and json.loads(lines[-3]) == {'status': 'HELD', 'exit_code': 13}
    internal = json.loads(lines[-2])
    assert list(internal) == STATUS_KEYS and internal['status'] == 'HELD' and internal['exit_code'] == 30 and 'boom' in internal['reason']


# ------------------------------------------------------------------- top level, plan mode only (ps_toplevel_smoke.py)
# The REAL script top level (param block, binding, exit mapping: the 2026-10-11 17:22 failure class) with the host stubbed;
# the helper refuses -Apply. RUN_427_R5_SITTING.ps1 S9 runs '-BuildDirectory <S09 build dir> -Attempt vC' (plan, then -Apply).
# The stub world has no build directory, so the plan must end in the stager's own HELD document (phase DECISION, exit 10)
# after the parameter, host, identity, constants and helper-import phases, never in a PowerShell error.

SMOKE_BUILD = r'C:\Program Files\CoChem\R5Sitting4.2.7-windows-20261011-v2\S09-build-20261011-190000'


@pytest.mark.parametrize('invocation', ['file', 'command'])
@pytest.mark.parametrize('attempt', ['v1', 'v2', 'v12'])
def test_toplevel_documented_sitting_call_reaches_the_decision_read(attempt, invocation):
    result = smoke.run_toplevel(SCRIPT, ['-BuildDirectory', SMOKE_BUILD, '-Attempt', attempt], invocation=invocation)
    result.raise_for_harness()
    assert not result.denied and result.error is None and not result.binding_error, result.describe()
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    status = json.loads(lines[-1])
    assert list(status) == STATUS_KEYS and (status['status'], status['exit_code'], result.exit_code) == ('HELD', 10, 10), result.describe()
    assert status['reason'] == 'The build directory does not exist: ' + SMOKE_BUILD
    held = json.loads('\n'.join(lines[:-1]))
    assert held['schema'] == 'cochem-config-only-staging-held/2' and held['phase'] == 'DECISION' and held['changed'] is False
    assert held['target_path'] == f'C:\\Program Files\\CoChem\\WardenConfig4.2.7-windows-20261011-r5-{attempt}\\pipeline.json'
