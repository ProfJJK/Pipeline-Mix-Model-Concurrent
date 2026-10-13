"""Inert PowerShell receipt/console contract tests; no tasks/children/providers."""
from pathlib import Path
import hashlib
import json

import pytest

from pipeline_tests import test_install_r6_runtime as fixture

SCRIPT = Path(__file__).parents[1]/'scripts/login_pipeline_worker_agy_terminal.ps1'


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(fixture, 'SCRIPT', SCRIPT)
    return fixture.run_ps


@pytest.mark.parametrize('mutation', ['', 'secret', 'module', 'system', 'model', 'cleanup', 'terminal', 'slot', 'partial-code', 'sid'])
def test_accepted_receipt_requires_complete_input_cleanup_and_pinned_identity(run_ps, mutation):
    root = Path(__file__).parents[1]
    module_pin = hashlib.sha256((root/'src/cochem_pipeline/attended_agy_terminal.py').read_bytes()).hexdigest()
    bridge_pin = hashlib.sha256((root/'scripts/worker_agy_terminal_bridge.py').read_bytes()).hexdigest()
    receipt = dict(schema='cochem-interactive-agy-terminal-login/1', transport='CONPTY_MANUAL_GOOGLE',
        slot='slot1', nonce='1'*32, login_mode='terminal', system_sid='S-1-5-18',
        helper_sha256=bridge_pin, terminal_module_sha256=module_pin,
        parent_bridge_sha256='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9',
        support_sha256='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839',
        native_executable_sha256='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741',
        native_executable_sha256_after='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741',
        cleanup_verified=True, terminal_cleanup_verified=True, secret_published=False,
        native_output_after_input_published=False, model_jobs_executed=0, login_commands_executed=1,
        one_line_submitted=True, code_write_completed=True, input_file_deleted=True,
        input_closed_marker_written=True, activation_ready=False, authentication_verified=False,
        status='LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED', pause_marker_seen=False,
        process=dict(token_sid='S-1-5-21-worker', token_matches_selected_worker=True,
            image_matches_reviewed_executable=True, owned_job_membership_verified=True))
    changes = dict(secret=('secret_published', True), module=('terminal_module_sha256', 'a'*64),
                   system=('system_sid','S-1-5-32-544'), model=('model_jobs_executed', 1),
                   cleanup=('cleanup_verified',False), terminal=('terminal_cleanup_verified',False),
                   slot=('slot','slot2'), **{'partial-code':('code_write_completed',False)})
    if mutation in changes:
        key, value = changes[mutation]
        receipt[key] = value
    if mutation == 'sid':
        receipt['process']['token_sid'] = 'S-1-5-18'
    result = run_ps("$receipt='"+json.dumps(receipt)+"'|ConvertFrom-Json\n"+
        "$script:terminalBridgeHash='"+bridge_pin+"';$script:terminalHash='"+module_pin+"'\n"+
        "$script:bridgeHash='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9'\n"+
        "$script:supportHash='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'\n"+
        "$script:agyHash='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'\n"+
        r'''
function Get-AgyHistoryExpectedSid {param($Slot) 'S-1-5-21-worker'}
$refused=$false
try{Assert-AgyTerminalReceipt $receipt 'slot1' ('1'*32)}catch{$refused=$true}
@{refused=$refused}|ConvertTo-Json -Compress
''')
    assert result['refused'] is bool(mutation)


def test_keys_before_fresh_prompt_are_discarded_except_escape(run_ps):
    result = run_ps(r'''
$script:events=[Collections.Generic.List[string]]::new()
function Update-ClaudeCodeInput {param($State,$Key) $script:events.Add('buffered')}
$state=[pscustomobject]@{CancelRequested=$false}
Invoke-AgyTerminalKey $state ([ConsoleKeyInfo]::new('x',[ConsoleKey]::X,$false,$false,$false)) $false
Invoke-AgyTerminalKey $state ([ConsoleKeyInfo]::new([char]27,[ConsoleKey]::Escape,$false,$false,$false)) $false
$cancelled=$state.CancelRequested
Invoke-AgyTerminalKey $state ([ConsoleKeyInfo]::new('y',[ConsoleKey]::Y,$false,$false,$false)) $true
@{events=@($script:events);cancelled=$cancelled}|ConvertTo-Json -Compress
''')
    assert result == dict(events=['buffered'], cancelled=True)


def test_new_terminal_namespace_is_separate_from_spent_login_tasks(run_ps):
    result = run_ps(r'''
$script:cochemRoot='C:\fixture'
Set-AgyTerminalNames 'slot1' ('1'*32)
@{root=$script:sessionRoot;task=$script:taskName;args=(Get-AgyTerminalArguments 'slot1' ('1'*32))}|ConvertTo-Json -Compress
''')
    assert result['root'] == r'C:\fixture\InteractiveAgyTerminal427-r4-slot1-' + '1'*32
    assert result['task'] == 'CoChem-4.2.7-InteractiveAgyTerminal-r4-slot1-' + '1'*32
    assert '--login-mode' not in result['args']
    assert 'worker_agy_terminal_bridge.py' in result['args']


@pytest.mark.parametrize('mutation',['','runtime','revision','argv','extra-secret','bad-count-type','cleanup','process-time'])
def test_full_production_receipt_keeps_runtime_revision_argv_and_process_proof(run_ps,mutation):
    # Uses the actual shared marker/runtime classifier definitions; no host reads.
    history=str(Path(__file__).parents[1]/'docs/deployment/windows-deployment-next/agy-session-history-r4-v1.ps1').replace("'","''")
    result=run_ps(r'''
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('HISTORY',[ref]$tokens,[ref]$errors)
foreach($f in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){. ([scriptblock]::Create($f.Extent.Text))}
Set-AgyTerminalConstants 'C:\fixture'
$pins=Get-AgyHistoryPins;$script:bridgeHash=$pins.bridge;$script:supportHash=$pins.support;$script:agyHash=$pins.agy
$sid='S-1-5-21-1-2-3-1001'
function Get-AgyHistoryExpectedSid {param($Slot) 'S-1-5-21-1-2-3-1001'}
$markers=@{before_input=@{};after_input=@{}}
foreach($phase in @('before_input','after_input')){foreach($name in @(Get-AgyHistoryMarkerNames $phase)){$markers[$phase][$name]=$false}}
$r=[ordered]@{schema='cochem-interactive-agy-terminal-login/1';transport='CONPTY_MANUAL_GOOGLE';slot='slot1';nonce=('1'*32);login_mode='terminal';
 native_arguments=@();system_sid='S-1-5-18';helper_sha256=$script:terminalBridgeHash;terminal_module_sha256=$script:terminalHash;parent_bridge_sha256=$pins.bridge;support_sha256=$pins.support;
 status='LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED';cleanup_verified=$true;terminal_cleanup_verified=$true;code_write_completed=$true;
 native_google_start_key_sent=$true;terminal_query_replies=1;terminal_hold_reason=$null;one_line_submitted=$true;input_file_deleted=$true;
 operator_cancelled=$false;terminated_after_input=$false;login_commands_executed=1;model_jobs_executed=0;authentication_verified=$false;activation_ready=$false;
 secret_published=$false;native_output_after_input_published=$false;native_output_bytes_before_input=1024;native_output_bound_reached_after_input=$false;
 native_output_published_bytes_before_input=500;native_output_bound_reached_before_input=$false;input_closed_marker_written=$true;pause_marker_seen=$false;
 native_markers=$markers;token_storage_observed=@{file_check='not_run';file_token_present=$null;file_token_bytes=$null;file_token_regular=$null;
  credential_manager_check='not_run';credential_manager_entry_present=$null;credential_manager_matching_entries=$null;token_contents_read=$false};
 started_at_unix_ms=1791850000000;finished_at_unix_ms=1791850001000;
 revision=@{schema='cochem-installed-revision/1';source_sha256=$pins.revision;files=109;acceptance_files=0;acceptance_sha256=$null;verified=$true;read_only=$true};
 runtime_root=$pins.runtime_root;install_receipt_sha256=$pins.install;source_manifest_sha256=$pins.manifest;config_sha256=$pins.config;resource_limits_sha256=$pins.resource;
 layout_sha256=$pins.layout_sha256;native_executable_sha256=$pins.agy;native_executable_sha256_after=$pins.agy;native_exit_code=0;
 process=@{token_sid=$sid;source='owned_windows_process_handle_and_child_token';profile_directory_sha256=('c'*64);pid=123;creation_time_filetime=134000000000000000;
  token_matches_selected_worker=$true;image_matches_reviewed_executable=$true;owned_job_membership_verified=$true}}
switch ('MUTATION'){
 'runtime'{$r.config_sha256=('d'*64)} 'revision'{$r.revision.files=110} 'argv'{$r.native_arguments=@('-p','INFERENCE')}
 'extra-secret'{$r.secret='DO-NOT-PUBLISH'} 'bad-count-type'{$r.model_jobs_executed=$false}
 'cleanup'{$r.terminal_cleanup_verified=$false} 'process-time'{$r.process.creation_time_filetime=0}}
$receipt=$r|ConvertTo-Json -Depth 8|ConvertFrom-Json
$action=[pscustomobject]@{Arguments=('-I -B "C:\fixture\worker_agy_terminal_bridge.py" --slot slot1 --nonce '+('1'*32))}
$actions=[pscustomobject]@{Action=$action};$actions|Add-Member ScriptMethod Item {param($n) $this.Action}
$task=[pscustomobject]@{LastTaskResult=0;Definition=[pscustomobject]@{Actions=$actions}}
$runtime=[pscustomobject]@{install_receipt_sha256=$pins.install;source_manifest_sha256=$pins.manifest;configuration_sha256=$pins.config;
 revision=[pscustomobject]@{source_sha256=$pins.revision}}
$held=$false;$proof=$null
try{$proof=Assert-AgyTerminalFullReceipt $receipt $task 'slot1' ('1'*32) 'terminal' $runtime $sid;Assert-AgyTerminalReceipt $receipt 'slot1' ('1'*32)}catch{$held=$true}
@{held=$held;accepted=($null -ne $proof -and $proof.accepted);auth=($null -ne $proof -and $proof.authentication_authorized_by_history)}|ConvertTo-Json -Compress
'''.replace('HISTORY',history).replace('MUTATION',mutation))
    assert result['held'] is bool(mutation),result
    if not mutation:
        assert result['accepted'] and not result['auth']


def test_wrapper_embedded_pins_match_exact_source():
    root=Path(__file__).parents[1]
    text=SCRIPT.read_text()
    for relative in ('src/cochem_pipeline/attended_agy_terminal.py','scripts/worker_agy_terminal_bridge.py'):
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest() in text


def test_public_report_is_allowlisted_and_omits_provider_text_and_secrets(run_ps):
    result=run_ps(r'''
$record=[pscustomobject]@{slot='slot1';nonce=('1'*32);phase='receipt';reason='NO_NATIVE_STARTUP_OUTPUT';
 cleanup_verified=$true;terminal_cleanup_verified=$true;receipt_sha256=('b'*64);error_type='DO-NOT-PUBLISH';
 raw_provider_output='PRIVATE-CODE';message='DO-NOT-PUBLISH';authorization_url='DO-NOT-PUBLISH'}
Get-AgyTerminalPublicProjection $record|ConvertTo-Json -Compress
''')
    assert result['reason']=='NO_NATIVE_STARTUP_OUTPUT' and result['cleanup_verified']
    assert result['receipt_sha256']=='b'*64
    assert 'PRIVATE-CODE' not in json.dumps(result) and 'DO-NOT-PUBLISH' not in json.dumps(result)
    assert not result['authentication_verified'] and not result['activation_ready']


@pytest.mark.parametrize('root',[r'C:\Users\ansac\outside',r'C:\Program Files\CoChem\R6Sitting4.2.7-windows-20261012-'+('a'*32)+r'\child',r'C:\Program Files\CoChem\other'])
def test_public_report_cannot_write_to_arbitrary_or_nested_roots(run_ps,root):
    result=run_ps("$held=$false;try{Assert-AgyTerminalPublicRoot '"+root+"'}catch{$held=$true}\n@{held=$held}|ConvertTo-Json -Compress")
    assert result['held']
