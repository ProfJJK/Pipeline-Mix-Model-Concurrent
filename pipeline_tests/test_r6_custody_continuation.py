"""Real temporary SQLite/files and inert protected-state/PowerShell adapters."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import r6_custody_amendment as amendment
from cochem_pipeline.knowledge import _protected as production_knowledge_protected
from pipeline_tests import test_install_r6_runtime as ps_fixture
from pipeline_tests.test_knowledge import corpus, portable_knowledge_permissions, ratify


def test_repair_accepts_only_exact_original_bytes_and_only_changes_directory_access():
    raw = (Path(__file__).parent / 'fixtures/r6_agy_agent_guard_359ca92.txt').read_bytes()
    module, digest = amendment.repaired_module(raw)
    assert digest == hashlib.sha256(raw.replace(b'0x20000 if directory else', b'0x20001 if directory else')).hexdigest()
    # Compare the complete fixed source to the frozen installed source repair.
    from cochem_pipeline import agy_agent_guard
    actual = ast.dump(ast.parse(inspect.getsource(agy_agent_guard)), include_attributes=False)
    repaired = ast.dump(ast.parse(raw.replace(b'0x20000 if directory else', b'0x20001 if directory else')), include_attributes=False)
    assert actual == repaired
    assert module.READ_DIRECTORY == agy_agent_guard.READ_DIRECTORY
    with pytest.raises(ValueError, match='binding differs'):
        amendment.repaired_module(raw + b'\n')


def test_installed_amendment_updates_both_acceptance_and_production_import(monkeypatch):
    from cochem_pipeline import agy_agent_guard as guard, r6_agent_acceptance as acceptance, windows as win
    from cochem_pipeline import r6_host_acceptance as host
    raw = (Path(__file__).parent / 'fixtures/r6_agy_agent_guard_359ca92.txt').read_bytes()
    old = guard.lock_worker_profile
    monkeypatch.setattr(guard, '__file__', str(amendment.ROOT / '.venv/Lib/site-packages/cochem_pipeline/agy_agent_guard.py'))
    monkeypatch.setattr(amendment.sys, 'prefix', str(amendment.ROOT / '.venv'))
    monkeypatch.setattr(amendment.sys, 'executable', str(amendment.ROOT / '.venv/Scripts/python.exe'))
    monkeypatch.setattr(win, 'require_system', lambda: None)
    def read(win, path, expected, maximum):
        assert expected in (amendment.ORIGINAL, 'e' * 64)
        return raw if expected == amendment.ORIGINAL else b'fixture helper'
    monkeypatch.setattr(host, 'read_bound', read)
    # Register monkeypatch cleanup before the implementation mutates aliases.
    monkeypatch.setattr(guard, 'lock_worker_profile', old)
    monkeypatch.setattr(acceptance, 'lock_worker_profile', acceptance.lock_worker_profile)
    try:
        result = amendment.install('e' * 64)
        assert guard.lock_worker_profile is acceptance.lock_worker_profile and guard.lock_worker_profile is not old
        assert guard.lock_worker_profile.__globals__['AgentGuardError'] is guard.AgentGuardError
        assert result['directory_desired_access'] == 0x20001
        assert not result['installed_files_modified'] and not result['acl_modified']
        with pytest.raises(ValueError, match='already amended'):
            amendment.install('e' * 64)
    finally:
        if hasattr(guard, '_r6_custody_amendment'):
            del guard._r6_custody_amendment


@pytest.mark.parametrize('fault', ['', 'generation', 'hash', 'authority', 'metadata', 'private_acl'])
def test_completed_knowledge_is_read_only_and_never_refreshed(corpus, monkeypatch, fault):
    from cochem_pipeline import windows as win, r6_host_acceptance as host, knowledge, knowledge_authority
    corpus.docs['.sources/reference.md'] += '\n' + ('Published immutable evidence and verified recovery. ' * 1800)
    ratify(corpus.root, corpus.docs)
    corpus.service.refresh()
    pointer, _ = corpus.service._current()
    evidence = dict(corpus.service.status(), authority_matches_capture=True)
    receipt = dict(phase='knowledge', status='PHASE_COMPLETED', manifest_sha256=amendment.MANIFEST,
        candidate_sha256=amendment.CANDIDATE, result=dict(status='NEW_KNOWLEDGE_AUTHORITY_VERIFIED', evidence=evidence))
    if fault == 'generation': evidence['generation'] = 'g-' + '0' * 32
    if fault == 'metadata': evidence['manifest_sha256'] = '0' * 64
    data = json.dumps(receipt).encode()
    # Keep the production separation between Program Files code and private
    # ProgramData state. A blanket no-op here hid use of the wrong validator.
    def code_path(path):
        raise win.WindowsIsolationError('Private state is not privileged code')
    ordinary = SimpleNamespace(validate_code_path=code_path)
    original = host.read_bound
    def read(win, path, expected=None, maximum=16777216):
        if path == amendment.KNOWLEDGE:
            if fault == 'hash': raise ValueError('fixture pinned receipt changed')
            assert expected == amendment.KNOWLEDGE_HASH
            return data
        return original(ordinary, path, expected, maximum)
    monkeypatch.setattr(host, 'read_bound', read)
    monkeypatch.setattr(win, 'validate_private_directory', lambda path: path.stat())
    private_reads = []
    def private_path(path):
        assert any(root == path or root in path.parents for root in (corpus.private, corpus.root))
        if fault == 'private_acl' and path.name == 'current.json':
            raise win.WindowsIsolationError('Private pointer ACL is not accepted')
        path.stat()
        if Path(corpus.config.state_root) in path.parents:
            private_reads.append(path.name)
    monkeypatch.setattr(win, 'validate_private_path', private_path)
    monkeypatch.setattr(knowledge, '_protected', production_knowledge_protected)
    def status(self, *, force):
        return dict(self.knowledge.status(), authority_matches_capture=fault != 'authority')
    monkeypatch.setattr(knowledge_authority.KnowledgeAuthority, '__init__', lambda self, service, captured: setattr(self, 'knowledge', service))
    monkeypatch.setattr(knowledge_authority.KnowledgeAuthority, 'status', status)
    monkeypatch.setattr(knowledge.KnowledgeService, 'refresh', lambda *a, **k: pytest.fail('rebuild forbidden'))
    state = Path(corpus.config.state_root)
    def snapshot():
        return {str(p.relative_to(state)): (p.read_bytes(), p.stat().st_mtime_ns) for p in state.rglob('*') if p.is_file()}
    before = snapshot()
    if fault:
        expected = win.WindowsIsolationError if fault == 'private_acl' else ValueError
        with pytest.raises(expected): amendment.verify_existing_knowledge(SimpleNamespace(knowledge=corpus.config))
    else:
        result = amendment.verify_existing_knowledge(SimpleNamespace(knowledge=corpus.config))
        assert result['status'] == 'EXISTING_KNOWLEDGE_AUTHORITY_VERIFIED'
        assert result['generation'] == pointer['generation'] and result['integrity_check'] == 'ok'
        assert not result['rebuilt'] and not result['existing_state_modified']
        assert private_reads.count('current.json') >= 2 and private_reads.count('knowledge_index.db') >= 2
        assert_activation_accepts_written_knowledge(monkeypatch, result)
    assert snapshot() == before


def ps(monkeypatch, script, body):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1] / 'scripts' / script)
    return ps_fixture.run_ps(body)


@pytest.mark.parametrize('failure', [FileNotFoundError, PermissionError])
def test_system_knowledge_check_refuses_missing_or_inaccessible_state_before_service_creation(tmp_path, monkeypatch, failure):
    from cochem_pipeline import windows as win, r6_host_acceptance as host, knowledge
    state = tmp_path / 'private-knowledge'
    receipt = dict(phase='knowledge', status='PHASE_COMPLETED', manifest_sha256=amendment.MANIFEST,
        candidate_sha256=amendment.CANDIDATE, result=dict(status='NEW_KNOWLEDGE_AUTHORITY_VERIFIED'))
    events = []
    def read(win, path, expected=None, maximum=16777216):
        assert path == amendment.KNOWLEDGE and expected == amendment.KNOWLEDGE_HASH
        events.append('receipt')
        return json.dumps(receipt).encode()
    def validate(path):
        assert path == state
        events.append('private-directory')
        raise failure('inert SYSTEM permission boundary')
    monkeypatch.setattr(host, 'read_bound', read)
    monkeypatch.setattr(win, 'validate_private_directory', validate)
    monkeypatch.setattr(knowledge, 'KnowledgeService', lambda *a, **k: pytest.fail('must not create or refresh state'))
    with pytest.raises(failure):
        amendment.verify_existing_knowledge(SimpleNamespace(knowledge=SimpleNamespace(state_root=str(state))))
    assert events == ['receipt', 'private-directory']
    assert not state.exists()


def assert_activation_accepts_written_knowledge(monkeypatch, result):
    # Feed the Python producer's actual result to the PowerShell consumer.
    # Other phases are explicitly inert receipts; no host evidence is claimed.
    body = "$script:knowledge='" + json.dumps(result).replace("'", "''") + "'|ConvertFrom-Json\n"
    body += r'''
function Test-Path {param($LiteralPath) $false}
function Assert-PrivateAcl {param($Path)}
function Test-ExactBool {param($Value,$Expected) ($Value -is [bool]) -and ($Value -eq $Expected)}
function Read-R3Control {param($Path,$Hash,$Bound) $Path}
function Read-R3Text {param($Path)
 $phase=($Path -split 'v1-')[1].Split('-')[0]
 $stamp=@{schema='cochem-r6-directory-custody-amendment/1';helper_sha256=('d'*64);original_guard_sha256='d86c90750dc2112ce8ff1bc9a4937898eb35cadbf4362050b04381e2138e6591';repaired_guard_sha256='6d8cce1fb2896a489c522f79c639256b9b296b8a92db6edc4f006f2105d1e9bf';directory_desired_access=131073;directory_share_mode=3;installed_files_modified=$false;acl_modified=$false}
 $stamp.tool_registry_amendment=@{schema='cochem-r6-agy-registry-amendment/1';protocol_sha256='2738b76b140e5bc25860c78a457dd91464b57681b607e44096d4d3bc30317ce2';worker_sha256='cb528d87f75c9b05f653aea0d3c23370e5d0f0632869afaca4d37be4e68bf147';executable_sha256='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741';agent_sha256='5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810';advertised_registry_scope='cli_builtin_runners';codex_workspace_selection='validated_process_cwd';agent_identity_required=$true;actual_tool_steps_rejected=$true;installed_files_modified=$false}
 $r=switch($phase){
  auth {@{status='ALL_SESSIONS_VERIFIED';checks=@(1..18|ForEach-Object {@{authenticated=$true}})}}
  agent {@{status='SIX_WORKER_AGENT_CUSTODY_VERIFIED';agent_custody_amendment=$stamp}}
  knowledge {$script:knowledge}
  preview {@{identities=@();database=@{schema_changes=@();migration_executed=$false}}}
  native {@{status='NATIVE_ACCEPTANCE_PARTIAL_AVAILABILITY';count=26;agent_custody_amendment=$stamp;
   targets=@(1..26|ForEach-Object {@{status='NOT_PROBED_POOL_UNAVAILABLE';provider='codex';model='fixture'}});
   owner_retirement=@{schema='cochem-owner-model-retirement/1';decision='owner-2026-10-12-pro-retired';helper_sha256=('f'*64);original_plan_sha256=('9'*64);retired_target=@{provider='gemini';model='gemini-3.1-pro';reasoning_effort='high'};retired_status='OWNER_RETIRED_MODEL_NOT_PROBED';retired_model_jobs_executed=0;replacement_selected=$false}}}
 }
 @{schema='cochem-r6-system-phase/1';phase=$phase;status='PHASE_COMPLETED';manifest_sha256=('a'*64);candidate_sha256=('b'*64);revision=@{verified=$true;source_sha256=('c'*64)};native_plan_sha256=('9'*64);result=$r}|ConvertTo-Json -Depth 18 -Compress
}
$index=@{schema='cochem-r6-acceptance-index/1';manifest_sha256=('a'*64);candidate_sha256=('b'*64);
phases=@('auth','agent','knowledge','native','preview'|ForEach-Object {@{phase=$_;receipt_sha256=('0'*64);receipt_path=('C:\Program Files\CoChem\R6Acceptance4.2.7-windows-20261012-v1-'+$_+'-'+('1'*32)+'\result.json')}})}
@{revision=(Assert-R6AcceptanceIndex $index ('a'*64) ('b'*64) ('f'*64) ('d'*64))}|ConvertTo-Json -Compress
'''
    assert ps(monkeypatch, 'activate_r6_runtime.ps1', body)['revision'] == 'c'*64


@pytest.mark.parametrize('hold', ['', 'verification', 'auth', 'knowledge', 'agent', 'native', 'preview', 'activation'])
@pytest.mark.parametrize('native_continuation', [False, True])
def test_continuation_reuses_completed_work_and_binds_identical_repair_to_startup(monkeypatch, hold, native_continuation):
    result = ps(monkeypatch, 'run_r6_launch.ps1', r'''
$script:events=[Collections.Generic.List[string]]::new();$script:SittingRoot='C:\fixture';$script:R6CutoverRequested=$false
$script:R6Pins=@{};foreach($name in @('install_r6_runtime.ps1','run_r6_system_phase.ps1','r6_native_retirement.py','r6_retirement_guard.py','r6_custody_amendment.py','r6_retarget_core.ps1')){$script:R6Pins[$name]='a'*64}
$script:R5=@{base_source=@{kind='r4-restore';source_attempt='v8';stop_attempt='v8'}}
$manifest=[pscustomobject]@{auth_recovery='20261012-first-auth-hold';verified_signin_continuation='20261013-six-agy-verified-r4-v7';
agent_custody_continuation='20261013-reviewed-agent-hold-r4-v8';manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4';candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'}
if(NATIVE){$manifest|Add-Member NoteProperty native_registry_continuation '20261013-reviewed-codex-cwd-hold-r4-v10'}
function Invoke-R5Stage0 {$script:events.Add('inspection')}
function Invoke-R5Stage2 {if(NATIVE){throw 'wrong stop path'};$script:events.Add('stop')}
function Invoke-R6NativeContinuationStop {if(-not NATIVE){throw 'unexpected recovery stop'};$script:events.Add('stop')}
function Invoke-R6LaunchChild {param($Name,$Arguments,[switch]$Attended)
 if($Attended){throw 'must not prompt'}
 if($Name -ceq 'verify_r6_auth_recovery.ps1'){
  $script:events.Add('verification');if('-AgentCustodyContinuation' -notin $Arguments){throw 'wrong recovery'}
  if(NATIVE -and '-NativeRegistryContinuation' -notin $Arguments){throw 'missing native history binding'}
  if('HOLD' -eq 'verification'){throw 'fixture'}
  return @{status='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED'}}
 if($Name -ceq 'run_r6_system_phase.ps1'){
  $phase=$Arguments[1];$script:events.Add($phase)
  if($phase -in @('knowledge','agent','native') -and '-CustodyAmendmentSha256' -notin $Arguments){throw 'missing phase repair'}
  if($phase -eq 'HOLD'){throw 'fixture'}
  return @{phase=$phase;result=@{status='ALL_SESSIONS_VERIFIED'};receipt_path='fixture';receipt_sha256=('b'*64)}}
 if($Name -ceq 'activate_r6_runtime.ps1'){
  $script:events.Add('activation');if('-CustodyAmendmentSha256' -notin $Arguments -or '-RetirementGuardSha256' -notin $Arguments){throw 'missing runtime repair'}
  if('HOLD' -eq 'activation'){throw 'fixture'}
  return @{status='WARDEN_R6_RUNNING_HEALTH_VERIFIED'}}
 throw ('unexpected child: '+$Name)
}
function Write-Host {param($Object,$ForegroundColor)}
function Write-R6PublicStatus {param($Status,$Result)}
function Save-R6AuthSummary {param($Result)}
function Write-R5RecordText {param($Path,$Text) $script:events.Add('index');'c'*64}
function Get-R5FreeAttempt {param($Prefix) 'v1'}
$errorText=$null;try{Invoke-R6LaunchSequence $manifest}catch{$errorText=$_.Exception.Message}
@{events=@($script:events);error=$errorText;cutover=$script:R6CutoverRequested}|ConvertTo-Json -Compress
'''.replace('HOLD', hold).replace('NATIVE', '$true' if native_continuation else '$false'))
    expected = ['inspection', 'verification', 'stop', 'auth', 'knowledge', 'agent', 'native', 'preview', 'index', 'activation']
    if hold: expected = expected[:expected.index(hold)+1]
    assert result['events'] == expected, result
    assert result['error'] == ('fixture' if hold else None)
    assert result['cutover'] is (hold in ('', 'activation'))


@pytest.mark.parametrize('fault', ['', 'hash', 'access', 'share', 'acl', 'installed'])
def test_activation_refuses_an_unmatched_or_weakened_repair(monkeypatch, fault):
    result = ps(monkeypatch, 'activate_r6_runtime.ps1', r'''
function Test-ExactBool {param($Value,$Expected) ($Value -is [bool]) -and ($Value -eq $Expected)}
$v=@{schema='cochem-r6-directory-custody-amendment/1';helper_sha256=('a'*64);original_guard_sha256='d86c90750dc2112ce8ff1bc9a4937898eb35cadbf4362050b04381e2138e6591';repaired_guard_sha256='6d8cce1fb2896a489c522f79c639256b9b296b8a92db6edc4f006f2105d1e9bf';directory_desired_access=131073;directory_share_mode=3;installed_files_modified=$false;acl_modified=$false}
switch('FAULT'){'hash'{$v.helper_sha256='c'*64};'access'{$v.directory_desired_access=131072};'share'{$v.directory_share_mode=7};'acl'{$v.acl_modified=$true};'installed'{$v.installed_files_modified=$true}}
$held=$false;try{Assert-R6CustodyAmendment $v ('a'*64)}catch{$held=$true}
$context=@{config_path='C:\fixture\pipeline.json';queue_launch_output_root='C:\fixture\queue';action=@{}}
Set-R6RetirementContext $context 'C:\Program Files\CoChem\R6Retirement4.2.7-windows-20261013-v1\r6_retirement_guard.py' ('d'*64) ('a'*64)
@{held=$held;arguments=$context.action.arguments;custody=$context.custody_amendment}|ConvertTo-Json -Compress
'''.replace('FAULT', fault))
    assert result['held'] is bool(fault)
    assert result['arguments'].endswith('--custody-sha256 ' + 'a' * 64)
    assert result['custody']['sha256'] == 'a' * 64


@pytest.mark.parametrize('fault', ['', 'restore', 'cleanup', 'knowledge', 'later_phase', 'active_task'])
def test_specific_post_agent_history_is_verified_without_resetting_old_evidence(monkeypatch, fault):
    result = ps(monkeypatch, 'verify_r6_auth_recovery.ps1', r'''
$script:base='C:\fixture';$script:targetRoot='C:\fixture\r6'
$script:events=[Collections.Generic.List[string]]::new()
function Read-R6RecoveryJson {param($Path,$Hash)
 $script:events.Add([IO.Path]::GetFileName($Path))
 if($Path -like '*install-manifest.json'){return @{}}
 if($Path -like '*pipeline.json'){return @{knowledge=@{state_root='C:\fixture\knowledge'}}}
 if($Path -like '*install-after.json'){return @{status='STOPPED_RUNTIME_INSTALLED';manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4';source_commit='359ca92e57b2d74eb407b258cf53123d80ef1467'}}
 if($Path -like '*status.json'){
  if($Hash -cne 'c124feb02e72f061109624993cb0538ef0ebe30431a3c2eeff39f659ca3b7f0c'){throw 'unbound diagnostic'}
  return @{status='DIAGNOSTIC_CAPTURED';workers=@(@{failure=@{reason='CUSTODY_ACCESS_NOT_DENIED'};handle_cleanup_observed=('FAULT' -ne 'cleanup')})}}
 if($Path -like '*start-receipt.json'){
  if($Hash -cne '3cd7e7f1826acc141f7e7144f03c062e32162d5be0a7b6282d82aba3db13fbc4'){throw 'unbound restore'}
  return @{schema='cochem-warden-start/3';status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED';target='r4';attempt=$(if('FAULT' -eq 'restore'){'v7'}else{'v8'});enabled_after=$true;running_instances=1;health=@{samples_stable=$true}}}
 $phase=($Path -split 'v1-')[1].Split('-')[0]
 $result=@{status='NEW_KNOWLEDGE_AUTHORITY_VERIFIED'}
 if($phase -eq 'auth'){$result=@{status='ALL_SESSIONS_VERIFIED';checks=@(1..18|ForEach-Object {@{authenticated=$true;cleanup_verified=$true}})}}
 if($phase -eq 'knowledge' -and 'FAULT' -eq 'knowledge'){$result.status='changed'}
 @{schema='cochem-r6-system-phase/1';phase=$phase;status=$(if($phase -eq 'agent'){'HELD_PRESERVE_PARTIAL'}else{'PHASE_COMPLETED'});manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4';candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288';result=$result}
}
function Test-Path {param($LiteralPath,$PathType)
 if($LiteralPath -ceq 'C:\fixture\knowledge'){
  $script:events.Add('owner-private-knowledge-probe')
  throw [UnauthorizedAccessException]::new('SYSTEM-private fixture denies the owner')}
 $false}
function Get-ChildItem {param($LiteralPath,[switch]$Directory)
 @([pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-knowledge-47776d31bd0e4773be318bde56f5be0a'},
 [pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-agent-0269bb0c420b488bbb4874841be21ea0'})
 if('FAULT' -eq 'later_phase'){[pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-native-unknown'}}}
function New-Object {param($ComObject)
 if($ComObject -cne 'Schedule.Service'){throw 'unexpected COM'}
 $s=[pscustomobject]@{};$s|Add-Member ScriptMethod Connect {}
 $s|Add-Member ScriptMethod GetFolder {param($Path)
  $f=[pscustomobject]@{};$f|Add-Member ScriptMethod GetTasks {param($Flags)
   $t=[pscustomobject]@{Name='CoChem-4.2.7-R6Acceptance-agent-prior';State=$(if('FAULT' -eq 'active_task'){4}else{3})}
   $t|Add-Member ScriptMethod GetInstances {param($Flags) @{Count=0}};$t};$f};$s}
function Assert-R6NotReferenced {$script:events.Add('not_referenced')}
function Assert-R6Tree {$script:events.Add('tree')}
function Assert-R6Interpreter {$script:events.Add('interpreter')}
$errorText=$null;$value=$null;try{$value=Assert-R6CustodyContinuationEvidence}catch{$errorText=$_.Exception.Message}
@{error=$errorText;events=@($script:events);verification=$value}|ConvertTo-Json -Compress
'''.replace('FAULT', fault))
    assert 'owner-private-knowledge-probe' not in result['events'], result
    assert bool(result['error']) is bool(fault), result
    if not fault:
        assert result['events'][-3:] == ['not_referenced', 'tree', 'interpreter']
        assert result['verification']['knowledge_state_verification'] == 'REQUIRED_IN_SYSTEM_KNOWLEDGE_PHASE'
        assert result['verification']['knowledge_state_verified'] is False


def test_daemon_entry_point_installs_pinned_custody_before_start(monkeypatch):
    from scripts import r6_retirement_guard as startup
    from cochem_pipeline import windows as win, r6_host_acceptance as host, __main__ as cli
    events = []
    monkeypatch.setattr(startup.sys, 'prefix', str(startup.ROOT / '.venv'))
    monkeypatch.setattr(startup.sys, 'executable', str(startup.ROOT / '.venv/Scripts/python.exe'))
    monkeypatch.setattr(win, 'require_system', lambda: events.append('system'))
    # Trusted helper fixture records only; daemon fixture never launches anything.
    raw = b'def install(expected, *, registry):\n    assert registry is True\n    assert expected == "' + b'a'*64 + b'"\n'
    def read(win, path, expected, maximum=16777216):
        events.append(path.name)
        if path.name == 'r6_custody_amendment.py':
            assert expected == 'a'*64
            return raw
        return b'fixture'
    monkeypatch.setattr(host, 'read_bound', read)
    monkeypatch.setattr(startup, 'apply_retirement', lambda *a: events.append('retirement'))
    monkeypatch.setattr(cli, 'daemon', lambda *a, **k: events.append('daemon'))
    monkeypatch.setattr(startup.sys, 'argv', ['startup', '--guard-sha256', 'b'*64, '--custody-sha256', 'a'*64,
        '--config', str(startup.ROOT/'pipeline.json'), '--queue-launch-output-root', 'fixture', '--docker-wait-seconds', '900'])
    startup.main()
    assert events == ['system', 'r6_retirement_guard.py', 'pipeline.json', 'r6_custody_amendment.py', 'retirement', 'daemon']


@pytest.mark.parametrize('fault', ['', 'raw', 'type', 'frame'])
def test_public_failure_metadata_survives_trailing_powershell_error_and_excludes_secrets(monkeypatch, fault):
    value = dict(schema='cochem-r6-amendment-failure/1', error_type='ValueError',
        frames=[dict(function='verify_worker', line=49, path='private path')],
        raw_error_published=False, message='secret credential')
    if fault == 'raw': value['raw_error_published'] = True
    if fault == 'type': value['error_type'] = 'secret credential'
    if fault == 'frame': value['frames'][0]['function'] = 'https://private.example'
    body = "$text='private preamble'+\"`n\"+'" + json.dumps(value) + "'+\"`n\"+'PowerShell error text'\n"
    body += '@{value=(Read-R6AmendmentFailure $text)}|ConvertTo-Json -Depth 6 -Compress'
    result = ps(monkeypatch, 'run_r6_launch.ps1', body)['value']
    if fault: assert result is None
    else: assert result == dict(error_type='ValueError', frames=[dict(function='verify_worker', line=49)])


@pytest.mark.parametrize('cause_name', ['AgyIdentityError', 'AgyToolRegistryError'])
def test_native_failure_preserves_category_and_cause_through_public_projection(monkeypatch, cause_name):
    from scripts.r6_custody_amendment import failure_projection
    from cochem_pipeline import agy_protocol
    from cochem_pipeline.failures import ProviderFailure
    try:
        try:
            raise getattr(agy_protocol, cause_name)('private provider output')
        except ValueError as cause:
            raise ProviderFailure('compatibility') from cause
    except ProviderFailure as error:
        value = failure_projection(error)
    assert value['error_type'] == 'ProviderFailure'
    assert value['category'] == 'compatibility'
    assert value['cause_type'] == cause_name
    assert 'private provider output' not in json.dumps(value)
    body = "$text='" + json.dumps(value) + "'+\"`n\"+'PowerShell terminating error'\n"
    body += '@{value=(Read-R6AmendmentFailure $text)}|ConvertTo-Json -Depth 6 -Compress'
    result = ps(monkeypatch, 'run_r6_launch.ps1', body)['value']
    assert result == {key: value[key] for key in ('error_type', 'category', 'cause_type', 'frames')}


def test_failure_projection_never_copies_unknown_types_or_categories():
    from scripts.r6_custody_amendment import failure_projection
    private_type = type('private-provider-text', (Exception,), {})
    error = private_type('secret credential')
    error.category = 'private-provider-text'
    error.__cause__ = private_type('private response')
    value = failure_projection(error)
    assert value['error_type'] == value['cause_type'] == 'OtherError'
    assert 'category' not in value
    assert 'private' not in json.dumps(value) and 'secret' not in json.dumps(value)


@pytest.mark.parametrize('field', ['category', 'cause_type'])
def test_public_failure_rejects_unrecognized_optional_metadata(monkeypatch, field):
    value = dict(schema='cochem-r6-amendment-failure/1', error_type='ProviderFailure',
        frames=[], raw_error_published=False, **{field: 'secret credential'})
    body = "$text='" + json.dumps(value) + "'\n"
    body += '@{value=(Read-R6AmendmentFailure $text)}|ConvertTo-Json -Depth 6 -Compress'
    assert ps(monkeypatch, 'run_r6_launch.ps1', body)['value'] is None
