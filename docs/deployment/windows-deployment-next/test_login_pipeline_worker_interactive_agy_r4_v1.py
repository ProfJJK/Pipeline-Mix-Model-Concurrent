"""Inert harness for login_pipeline_worker_interactive_agy_r4_v1.ps1 (Gemini build-manifest step 4).

The wrapper is never run with -Apply, and as a script only by the top-level smoke tests at the end (ps_toplevel_smoke.py:
stubbed host, plan mode). Otherwise its functions are dot-sourced from the AST into a
non-interactive powershell.exe; the console key source, Task Scheduler, protected-path checks, code-tree inspection
and history review are fixtures. The real console loop, prompt detection, packet hand-off, receipt binding (through the
real history classifier and real bridge receipts), session records and exit-code mapping are exercised. Every file
the fixtures create lives under pytest's tmp_path; no Program Files path, task, worker profile or credential is touched.
"""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import pytest

import ps_toplevel_smoke as smoke

W = Path(__file__).resolve().parent
spec =importlib.util.spec_from_file_location('agy_bridge_fixtures_for_wrapper', W / 'test_agy_login_bridge_r4_v1.py')
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)

WRAPPER = W / 'login_pipeline_worker_interactive_agy_r4_v1.ps1'
HISTORY = W / 'agy-session-history-r4-v1.ps1'
INPUT = W / 'claude-code-input-v6.ps1'
V6 = W / 'login_pipeline_worker_interactive_r3_v6.ps1'
STATUS = W / 'check-worker-native-status-r3.ps1'
REGISTER = W / 'register-stopped-warden-r3.ps1'
STAGE = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
q = fx.q
CODE = 'Q-fixture-PpQq+code'
NONCE = fx.NONCE
PRINT_PROMPT = 'Or, paste the authorization code here and press Enter: '
INTRO = 'Please visit the following URL to authorize the application:\nhttps://accounts.google.com/o/oauth2/auth?client_id=fixture\n'
REFUSAL = 'Print mode: not logged in and no controlling terminal; cannot complete interactive login\n'
NOTICE = 'Open the Google sign-in URL shown above in your own browser now.'
MASKED = 'Code (masked; Enter submits, Escape cancels): '
OTHER_INTRO = 'Please visit the following URL to authorize the application:\nhttps://accounts.example.invalid/o/oauth2/auth?client_id=fixture\n'
REFUSED = 'no code is accepted and none was written'
HELD = 'the code prompt is held'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ps_named(path, names):
    wanted = ','.join(q(name) for name in names)
    return ("$__tokens=$null;$__errors=$null;$__ast=[Management.Automation.Language.Parser]::ParseFile(" + q(path) + ",[ref]$__tokens,[ref]$__errors);"
            "if($__errors.Count){throw ($__errors|Out-String)};$__wanted=@(" + wanted + ");"
            "foreach($__f in $__ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){if($__f.Name -cin $__wanted){. ([scriptblock]::Create($__f.Extent.Text))}};\n")


def ps_text(value):
    """A PowerShell expression for an arbitrary string (control characters included)."""
    return '[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(' + q(base64.b64encode(value.encode()).decode()) + '))'


# ----- the real console loop with an inert key source -----

LOOP_STUBS = r'''
$script:tick=0;$script:done=$false;$script:events=[Collections.Generic.List[string]]::new()
$script:queue=[Collections.Generic.Queue[ConsoleKeyInfo]]::new()
$script:packets=0;$script:packetAttempts=0;$script:exact=$false;$script:packetTick=-1;$script:cancels=0
$script:hosts=[Collections.Generic.List[string]]::new();$script:lastSecret=$null;$script:state=$null
function Add-FixtureText([string]$Value){foreach($c in $Value.ToCharArray()){$script:queue.Enqueue([ConsoleKeyInfo]::new($c,[ConsoleKey]::NoName,$false,$false,$false))}}
function Add-FixtureKey([ConsoleKey]$Key){$script:queue.Enqueue([ConsoleKeyInfo]::new([char]0,$Key,$false,$false,$false))}
function Set-FixtureLog([string]$Text){[IO.File]::WriteAllText((Join-Path $root 'operator.log'),$Text,[Text.UTF8Encoding]::new($false))}
function Test-AgyConsoleKeyAvailable{return $script:queue.Count -gt 0}
function Read-AgyConsoleKey{
    $k=$script:queue.Dequeue()
    # The bridge leaves its read loop while the owner presses Enter (the 600 s window just ended).
    if($mode -ceq 'closed_on_enter' -and $k.Key -eq [ConsoleKey]::Enter){[IO.File]::WriteAllText((Join-Path $root 'input.closed'),'fixture closed marker')}
    return $k
}
function Write-Host{param($Object)$script:hosts.Add([string]$Object)}
$script:actualNew=(Get-Command New-ClaudeCodeInput).ScriptBlock
function New-ClaudeCodeInput{$value=& $script:actualNew;$script:state=$value;$value}
function Test-InstanceComplete{
    param($Instance)
    if(-not $Instance.fixture){throw 'Inert instance binding lost'}
    if($mode -ceq 'terminal_before_write' -and $null -ne (Get-Variable inputState -ErrorAction SilentlyContinue) -and $inputState.SubmissionRequested){return $true}
    return $script:done
}
function Write-CancelRequest{
    param($CancelRoot,$CancelNonce)
    if($CancelRoot -cne $root -or $CancelNonce -cne $nonce){throw 'Inert cancellation binding lost'}
    $script:cancels++;$script:events.Add('CANCEL');$script:done=$true
}
function Write-PrivatePacket{
    param($PacketPath,$PacketNonce,$Secret)
    if($PacketPath -cne (Join-Path $root 'input.once') -or $PacketNonce -cne $nonce){throw 'Inert packet binding lost'}
    if(-not $nativePromptReady -or $script:done){throw 'Input reached sink without a live ready prompt'}
    $script:packetAttempts++;$script:events.Add('PACKET');$script:lastSecret=$Secret
    if($mode -ceq 'packet_failure'){throw 'Inert packet failure'}
    $ptr=[IntPtr]::Zero
    try{$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret);$script:exact=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) -ceq $expected}
    finally{if($ptr -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}}
    $script:packets++;$script:packetTick=$script:tick
}
$script:actualClear=(Get-Command Clear-ClaudeConsoleInput).ScriptBlock
function Clear-ClaudeConsoleInput{
    $script:events.Add('DRAIN')
    if($mode -ceq 'uncleared_queue'){return [pscustomobject]@{console_queue_clear=$false;bound_reached=$true}}
    if($mode -ceq 'invalid_clear_metadata'){return [pscustomobject]@{console_queue_clear='true';bound_reached=$false}}
    & $script:actualClear -KeyAvailable {Test-AgyConsoleKeyAvailable} -ReadKey {Read-AgyConsoleKey}
}
function Start-Sleep{
    param($Milliseconds)
    if($Milliseconds -ne 100){throw 'Polling cadence changed'}
    $script:tick++
    if($script:tick -gt 6){throw 'Inert loop failed to terminate'}
    if($script:tick -eq 1){
        if($mode -ceq 'preprompt'){Set-FixtureLog ($fixtureIntro+$fixturePrompt)}
        elseif($mode -ceq 'splitprompt'){Set-FixtureLog ($fixtureIntro+$fixturePrompt);Add-FixtureText $expected;Add-FixtureKey Enter}
        elseif($mode -ceq 'after_submit_escape'){Add-FixtureKey Escape}
        elseif($mode -ceq 'after_submit_keys'){Add-FixtureText 'Q-extra-P';Add-FixtureKey Enter}
        else{$script:done=$true}
    }else{$script:done=$true}
}
$initial=$fixtureIntro+$fixturePrompt
if($mode -cin @('preprompt','no_prompt_terminal')){$initial=$fixtureIntro}
if($mode -ceq 'no_prompt_terminal'){$initial=$fixtureIntro+$fixtureRefusal}
if($mode -ceq 'splitprompt'){$initial=$fixtureIntro+$fixturePrompt.Substring(0,$split)}
if($mode -ceq 'log_over_bound'){$initial='x'*131073}
if($mode -ceq 'control_chars'){$initial=$fixtureIntro+[char]27+'[31mred'+[char]0x202E+'evil'+[char]7+"`n"+$fixturePrompt}
if($mode -ceq 'no_google_url'){$initial=$fixtureOther+$fixturePrompt}
if($mode -ceq 'google_url_after_prompt'){$initial=$fixturePrompt+"`n"+$fixtureIntro}
if($mode -ceq 'window_closed'){[IO.File]::WriteAllText((Join-Path $root 'input.closed'),'fixture closed marker')}
Set-FixtureLog $initial
if($mode -cne 'splitprompt'){
    if($mode -ceq 'cancel'){Add-FixtureText 'QP';Add-FixtureKey Escape;Add-FixtureText 'P-leftover';Add-FixtureKey Enter}
    elseif($mode -ceq 'empty_enter'){Add-FixtureKey Enter;Add-FixtureText $expected;Add-FixtureKey Enter}
    else{Add-FixtureText $expected;Add-FixtureKey Enter;Add-FixtureText 'Q-leftover';Add-FixtureKey Enter}
}
$deadline=[DateTime]::UtcNow.AddMinutes(5);if($mode -ceq 'deadline'){$deadline=[DateTime]::UtcNow.AddMinutes(-1)}
$instance=[pscustomobject]@{fixture=$true}
$original=[Console]::Out;$mask=[IO.StringWriter]::new();[Console]::SetOut($mask)
$failed=$false;$message='';$loop=$null
try{
    try{$loop=Invoke-AgyLoginConsoleLoop $instance $root $nonce $deadline}catch{$failed=$true;$message=$_.Exception.Message}
    $disposed=$true
    if($null -ne $script:lastSecret){$disposed=$false;try{$script:lastSecret.AppendChar([char]'X')}catch{$disposed=$_.Exception.GetBaseException() -is [ObjectDisposedException]}}
    $result=[ordered]@{failed=$failed;message=$message;loop=$loop;packets=$script:packets;packet_attempts=$script:packetAttempts;exact=$script:exact;packet_tick=$script:packetTick;
        cancels=$script:cancels;events=@($script:events.ToArray());hosts=@($script:hosts.ToArray());output=$mask.ToString();closed=$script:state.Closed;
        secret_null=($null -eq $script:state.Secret);disposed=$disposed;queued=$script:queue.Count}
}finally{[Console]::SetOut($original);$mask.Dispose()}
$result|ConvertTo-Json -Compress -Depth 8
'''


def loop_fixture(tmp_path, mode, split=0, prompt=PRINT_PROMPT):
    prefix = fx.ps_functions(WRAPPER) + fx.ps_functions(INPUT)
    prefix += "Set-AgyLoginConstants 'slot3' 'print' " + q(W) + "\n"
    prefix += '$root=' + q(tmp_path) + ';$nonce=' + q(NONCE) + ';$mode=' + q(mode) + ';$split=' + str(split) + ';$expected=' + q(CODE) + ';'
    prefix += '$fixturePrompt=' + ps_text(prompt) + ';$fixtureIntro=' + ps_text(INTRO) + ';$fixtureRefusal=' + ps_text(REFUSAL) + ';'
    prefix += '$fixtureOther=' + ps_text(OTHER_INTRO) + ';\n'
    return json.loads(fx.ps_run(prefix + LOOP_STUBS, timeout=60))


@pytest.mark.parametrize('mode', ['ready', 'preprompt', 'empty_enter', 'after_submit_keys', 'after_submit_escape'])
def test_actual_loop_accepts_p_q_once_without_echo_and_keeps_polling(tmp_path, mode):
    result = loop_fixture(tmp_path, mode)
    assert not result['failed'], result['message']
    assert result['packets'] == result['packet_attempts'] == 1 and result['exact']
    assert result['packet_tick'] == (1 if mode == 'preprompt' else 0)
    assert result['output'].count('*') == len(CODE)
    assert CODE not in result['output'] and 'Q-leftover' not in result['output'] and 'Q-extra' not in result['output']
    assert result['cancels'] == (1 if mode == 'after_submit_escape' else 0)
    assert result['closed'] and result['secret_null'] and result['disposed'] and result['queued'] == 0
    assert result['events'].count('PACKET') == 1 and result['output'].count(MASKED) == 1
    assert 'paste' not in result['output'] and result['output'].count(INTRO) == 1 and result['output'].count('Or, ') == 1
    assert result['hosts'].count(NOTICE) == 1
    assert result['loop'] == {'native_prompt_seen': True, 'one_line_submitted': True, 'cancel_requested': mode == 'after_submit_escape',
                              'input_window_closed': False, 'code_prompt_held': False}
    assert not any(REFUSED in line or HELD in line for line in result['hosts'])
    assert not any('One line submitted' in line for line in result['hosts'])  # the receipt, not the console, says it was fed


@pytest.mark.parametrize('mode', ['window_closed', 'closed_on_enter', 'terminal_before_write'])
def test_actual_loop_refuses_input_once_the_bridge_closed_its_window_or_the_task_ended(tmp_path, mode):
    """O-F6: after input.closed (or the task end) no code is written, and the console says so."""
    result = loop_fixture(tmp_path, mode)
    assert not result['failed'], result['message']
    assert result['packets'] == result['packet_attempts'] == 0 and result['cancels'] == 0 and 'PACKET' not in result['events']
    assert sum(REFUSED in line for line in result['hosts']) == 1
    assert result['loop']['input_window_closed'] is True and result['loop']['one_line_submitted'] is False
    assert result['closed'] and result['secret_null'] and result['queued'] == 0 and CODE not in result['output']
    # A closed window never shows the masked code prompt; a window that closes at Enter showed it once.
    assert result['output'].count(MASKED) == (0 if mode == 'window_closed' else 1)
    assert not (tmp_path / 'input.once').exists()


@pytest.mark.parametrize('mode', ['no_google_url', 'google_url_after_prompt'])
def test_actual_loop_holds_the_code_prompt_without_a_preceding_google_sign_in_url(tmp_path, mode):
    """O-F9: the masked prompt appears only after an https://accounts.google.com/ URL in the pre-input text."""
    result = loop_fixture(tmp_path, mode)
    assert not result['failed'], result['message']
    assert result['packets'] == result['packet_attempts'] == 0 and result['output'].count(MASKED) == 0
    assert sum(HELD in line for line in result['hosts']) == 1 and result['loop']['code_prompt_held'] is True
    assert result['loop']['native_prompt_seen'] is False and result['loop']['one_line_submitted'] is False
    assert result['closed'] and result['secret_null'] and CODE not in result['output']
    if mode == 'no_google_url':
        assert NOTICE not in result['hosts'] and 'accounts.example.invalid' in result['output']


@pytest.mark.parametrize('split', [1, 4, 5, 15, 27, 31])
def test_actual_loop_replaces_a_chunked_native_prompt_without_losing_the_url(tmp_path, split):
    result = loop_fixture(tmp_path, 'splitprompt', split)
    assert not result['failed'] and result['packets'] == 1 and result['exact'] and result['packet_tick'] == 1
    assert result['output'].count(INTRO) == 1 and result['output'].count('Or, ') == 1 and 'paste' not in result['output']
    assert result['output'].count(MASKED) == 1 and CODE not in result['output']
    assert result['output'].count('*') == len(CODE) and result['queued'] == 0


@pytest.mark.parametrize('prompt', ['Enter the authorization code: ', 'Paste the authorization code below: ', 'Or enter the redirect URL: ',
                                    'ENTER THE AUTHORIZATION CODE:'])
def test_every_reviewed_native_prompt_variant_is_recognised(tmp_path, prompt):
    result = loop_fixture(tmp_path, 'ready', prompt=prompt)
    assert not result['failed'] and result['packets'] == 1 and result['exact'] and result['output'].count(MASKED) == 1
    assert re.search(r'(?i)(paste|enter) the (authorization code|redirect url)', result['output']) is None


@pytest.mark.parametrize('mode,failed,cancels', [('cancel', False, 1), ('terminal_before_write', False, 0),
                                                 ('no_prompt_terminal', False, 0), ('packet_failure', True, 1),
                                                 ('deadline', True, 2), ('log_over_bound', True, 1)])
def test_actual_loop_cancel_terminal_deadline_and_missing_prompt_never_submit(tmp_path, mode, failed, cancels):
    result = loop_fixture(tmp_path, mode)
    assert result['failed'] == failed and result['packets'] == 0 and result['cancels'] == cancels
    assert result['packet_attempts'] == (1 if mode == 'packet_failure' else 0)
    assert result['closed'] and result['secret_null'] and result['disposed']
    assert CODE not in result['output'] and 'P-leftover' not in result['output']
    if mode == 'no_prompt_terminal':
        assert REFUSAL.strip() in result['output'] and result['loop']['native_prompt_seen'] is False
    if mode == 'deadline':
        assert result['message'].startswith('Login wrapper deadline reached')


@pytest.mark.parametrize('mode', ['uncleared_queue', 'invalid_clear_metadata'])
def test_actual_loop_requires_explicit_boolean_queue_clearing_proof(tmp_path, mode):
    result = loop_fixture(tmp_path, mode)
    assert result['failed'] and result['packets'] == 1 and result['cancels'] == 1
    assert result['message'] == 'Console input exceeded its clearing bound; preserve the session.'
    assert result['closed'] and result['secret_null'] and result['disposed'] and CODE not in result['output']


def test_console_display_strips_escape_control_and_bidi_characters(tmp_path):
    result = loop_fixture(tmp_path, 'control_chars')
    assert not result['failed'] and result['packets'] == 1
    assert '\x1b' not in result['output'] and '\u202e' not in result['output'] and '\x07' not in result['output']
    assert '[31mred' in result['output'] and 'evil' in result['output']


def test_prompt_detection_and_prefix_guard_table():
    cases = {'none': 'Please visit https://accounts.google.com/x\n', 'print': 'x Or, paste the authorization code here',
             'tui': 'Enter the authorization code:', 'redirect': 'Enter the redirect URL:', 'upper': 'PASTE THE AUTHORIZATION CODE',
             'partial': 'x Or, paste the authorization', 'prefix_e': 'Please', 'prefix_enter_the_r': 'Enter the r', 'no_prefix': 'done.\n'}
    body = fx.ps_functions(WRAPPER) + "$cases=" + "@{" + ';'.join(f"{k}={ps_text(v)}" for k, v in cases.items()) + "}\n" + r'''
$out=[ordered]@{};foreach($k in $cases.Keys){$out[$k]=[ordered]@{at=(Find-AgyNativePrompt $cases[$k]);hold=(Get-AgyPromptPrefixHold $cases[$k])}}
$out|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    assert result['none'] == {'at': -1, 'hold': 0} and result['no_prefix'] == {'at': -1, 'hold': 0}
    assert result['print']['at'] == 6 and result['tui']['at'] == 0 and result['redirect']['at'] == 0 and result['upper']['at'] == 0
    assert result['partial'] == {'at': -1, 'hold': len('paste the authorization')}
    assert result['prefix_e'] == {'at': -1, 'hold': 1} and result['prefix_enter_the_r'] == {'at': -1, 'hold': len('Enter the r')}


def test_code_prompt_requires_a_preceding_google_sign_in_url_table():
    google = 'Visit https://accounts.google.com/o/oauth2/auth?x\n'
    cases = {'google_then_prompt': google + 'Or, paste the authorization code here', 'upper_url': google.upper() + 'Enter the authorization code:',
             'prompt_only': 'Or, paste the authorization code here', 'other_url': 'Visit https://accounts.google.com.example.invalid/x\nEnter the redirect URL:',
             'lookalike': 'Visit https://accounts-google.com/x\npaste the authorization code', 'http': 'Visit http://accounts.google.com/x\npaste the authorization code',
             'prompt_then_google': 'Enter the authorization code: ' + google, 'reprompt': 'Enter the authorization code: ' + google + 'Enter the authorization code:',
             'url_without_prompt': google}
    body = fx.ps_functions(WRAPPER) + "$cases=" + "@{" + ';'.join(f"{k}={ps_text(v)}" for k, v in cases.items()) + "}\n" + r'''
$out=[ordered]@{};foreach($k in $cases.Keys){$out[$k]=[ordered]@{ready=(Find-AgyCodePrompt $cases[$k]);google=(Find-AgyGoogleSignInUrl $cases[$k])}}
$out|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    assert result['google_then_prompt']['ready'] == len(google) + 4 and result['upper_url']['ready'] == len(google)
    assert result['reprompt']['ready'] == len('Enter the authorization code: ' + google)
    for name in ('prompt_only', 'other_url', 'lookalike', 'http', 'prompt_then_google', 'url_without_prompt'):
        assert result[name]['ready'] == -1, name
    assert result['other_url']['google'] == -1 and result['lookalike']['google'] == -1
    assert result['prompt_then_google']['google'] == len('Enter the authorization code: Visit ')


# ----- host gate: -Apply needs the owner at an elevated, interactive, non-redirected ConsoleHost -----

GOOD_PROBE = ("[pscustomobject]@{edition='Desktop';is64=$true;computer='AETHERDESK';admin=$true;identity='AETHERDESK\\ansac';"
              "user_interactive=$true;input_redirected=$false;output_redirected=$false;host_name='ConsoleHost'}")


def test_apply_host_gate_table():
    body = fx.ps_functions(WRAPPER) + "$good=" + GOOD_PROBE + "\n" + r'''
function Test-Gate([bool]$Apply,[bool]$Interactive,$Probe){try{Assert-AgyLoginHost $Apply $Interactive $Probe;'ALLOWED'}catch{$_.Exception.Message}}
$out=[ordered]@{}
$out.real_plan=Test-Gate $false $false $null
$out.real_apply=Test-Gate $true $true $null
$out.good_apply=Test-Gate $true $true $good
$out.good_apply_without_interactive=Test-Gate $true $false $good
foreach($change in @(@('edition','Core'),@('is64',$false),@('computer','OTHERHOST'),@('admin',$false),@('identity','AETHERDESK\other'),@('user_interactive',$false),
                     @('input_redirected',$true),@('output_redirected',$true),@('host_name','Visual Studio Code Host'),@('admin','true'))){
    $probe=$good.PSObject.Copy();$probe.($change[0])=$change[1];$out[('apply_'+$change[0]+'_'+[string]$change[1])]=Test-Gate $true $true $probe
}
$plan=$good.PSObject.Copy();$plan.admin=$false;$plan.input_redirected=$true;$out.plan_unelevated_redirected=Test-Gate $false $false $plan
$other=$good.PSObject.Copy();$other.computer='OTHERHOST';$out.plan_other_host=Test-Gate $false $false $other
$out|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    refusal = 'Apply requires the owner at an elevated interactive ConsoleHost, with -Interactive and no redirected input/output.'
    assert result.pop('real_plan') == 'ALLOWED' and result.pop('good_apply') == 'ALLOWED'
    assert result.pop('plan_unelevated_redirected') == 'ALLOWED'
    assert result.pop('real_apply') == refusal and result.pop('good_apply_without_interactive') == refusal
    assert result.pop('apply_edition_Core') == result.pop('apply_is64_False') == result.pop('apply_computer_OTHERHOST') == \
        result.pop('plan_other_host') == 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'
    assert set(result.values()) == {refusal}, result


MAIN_PRELUDE = r'''
$script:calls=[Collections.Generic.List[string]]::new()
function Get-AgyLoginHelperDefinitions {$script:calls.Add('helpers');throw 'helper import must not be reached'}
$script:actualConstants=(Get-Command Set-AgyLoginConstants).ScriptBlock
function Set-AgyLoginConstants {param($Slot,$LoginMode,$ScriptRoot) $script:calls.Add('constants');& $script:actualConstants $Slot $LoginMode $ScriptRoot}
function Try-Main([hashtable]$Arguments){try{$code=Invoke-AgyLoginMain @Arguments;[ordered]@{ok=$true;code=$code;calls=@($script:calls)}}catch{[ordered]@{ok=$false;message=$_.Exception.Message;calls=@($script:calls)}}}
'''


def test_noninteractive_apply_is_refused_before_any_import_constant_or_task():
    body = fx.ps_functions(WRAPPER) + MAIN_PRELUDE + r'''
(Try-Main @{Slot='slot1';LoginMode='print';CaptureAttempt='';ApplyRequested=$true;InteractiveRequested=$true;ScriptRoot='C:\fixture-not-used'})|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    assert not result['ok'] and result['calls'] == []
    assert result['message'] == 'Apply requires the owner at an elevated interactive ConsoleHost, with -Interactive and no redirected input/output.'


@pytest.mark.parametrize('arguments,message', [
    ("Slot='slot1';LoginMode='none';CaptureAttempt=''", 'Gemini sign-in is held: the signed-out capture decided login mode none'),
    ("Slot='slot9';LoginMode='print';CaptureAttempt=''", 'Only the six configured worker slots are supported'),
    ("Slot='slot1';LoginMode='headless';CaptureAttempt=''", 'Only the login modes print, tui and none are defined'),
    ("Slot='slot1';LoginMode='print';CaptureAttempt=('0'*32)", 'A nonzero lowercase 32-hex -CaptureAttempt is required'),
])
def test_apply_refusals_happen_before_any_change_even_for_the_owner(arguments, message):
    body = fx.ps_functions(WRAPPER) + MAIN_PRELUDE + "function Get-AgyLoginHostProbe {" + GOOD_PROBE + "}\n" + \
        "(Try-Main @{" + arguments + ";ApplyRequested=$true;InteractiveRequested=$true;ScriptRoot='C:\\fixture-not-used'})|ConvertTo-Json -Compress"
    result = json.loads(fx.ps_run(body))
    assert not result['ok'] and result['message'].startswith(message) and result['calls'] == []


# ----- read-only plan through the real main with inert helpers -----

def capture_fixture(base, attempt, mode, *, gate=True, tamper=False, stage='signed-out'):
    root = Path(base) / f'AgyCapture4.2.7-windows-20261010-r4-v1-{attempt}-slot1-signed-out'
    root.mkdir(parents=True)
    login_mode = {'schema': 'cochem-agy-login-mode/1', 'attempt': attempt, 'nonce': 'e' * 32, 'slot': 'slot1', 'stage': stage,
                  'mode': mode, 'decided_by': {'print': 'P3', 'tui': 'P6'}.get(mode), 'evidence': {}, 'evidence_sha256': 'f' * 64}
    raw = json.dumps(login_mode, indent=2).encode('ascii')
    (root / 'login-mode.json').write_bytes(raw + (b' ' if tamper else b''))
    receipt = {'schema': 'cochem-agy-status-capture/1', 'attempt': attempt, 'nonce': 'e' * 32, 'slot': 'slot1', 'stage': 'signed-out',
               'status': 'CAPTURE_COMPLETE', 'gate': {'passed': gate, 'reasons': []},
               'login_mode': {'mode': mode, 'decided_by': login_mode['decided_by'], 'path': 'login-mode.json',
                              'sha256': hashlib.sha256(raw).hexdigest(), 'evidence_sha256': 'f' * 64}}
    (root / 'capture-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    return root


PLAN_PRELUDE = r'''
$script:fixtureRuntime=[ordered]@{install_receipt_sha256='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';source_manifest_sha256='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';configuration_sha256='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c';revision=[pscustomobject]@{source_sha256='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'}}
function Get-FixtureFunctionText([string]$Path,[string]$Name){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $Name},$true))[0].Extent.Text}
$script:stubDefinitions=@(
    (Get-FixtureFunctionText ''' + q(STAGE) + r''' 'Initialize-FileIdentity'),(Get-FixtureFunctionText ''' + q(STAGE) + r''' 'Open-VerifiedFile'),
    (Get-FixtureFunctionText ''' + q(STATUS) + r''' 'Read-R3Control'),(Get-FixtureFunctionText ''' + q(STATUS) + r''' 'Read-R3Text'),
    'function Assert-NoReparseAncestors {param([string]$Path)}','function Assert-ProtectedPath {param([string]$Path)}',
    'function Assert-R4InstalledBindings {if($script:runtimeFails){throw "fixture runtime differs"};$script:fixtureRuntime}',
    'function Assert-VenvBinding {param([string]$Text)}')
function Get-AgyLoginHelperDefinitions {$script:stubDefinitions}
$script:actualConstants=(Get-Command Set-AgyLoginConstants).ScriptBlock
function Set-AgyLoginConstants {param($Slot,$LoginMode,$ScriptRoot) & $script:actualConstants $Slot $LoginMode $ScriptRoot;$script:cochemRoot=$script:fixtureParent}
function Get-AgyLoginHostProbe {[pscustomobject]@{edition='Desktop';is64=$true;computer='AETHERDESK';admin=$false;identity='AETHERDESK\ansac';user_interactive=$true;input_redirected=$true;output_redirected=$true;host_name='ConsoleHost'}}
$script:pinsOpened=0
function Open-AgyLoginPins {$script:pinsOpened++}
function New-DaemonTask($Enabled,$State,$Instances){$t=[pscustomobject]@{Enabled=$Enabled;State=$State;InstanceCount=$Instances};$t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=$this.InstanceCount}};$t}
$script:fixtureFolder=[pscustomobject]@{Tasks=@{};Denied=@()}
$script:fixtureFolder|Add-Member ScriptMethod GetTask {param($name) if($name -cin $this.Denied){throw [Runtime.InteropServices.COMException]::new('fixture denied',-2147024891)};if($this.Tasks.ContainsKey($name)){return $this.Tasks[$name]};throw [Runtime.InteropServices.COMException]::new('fixture missing',-2147024894)}
function Connect-AgyTaskFolder {[pscustomobject]@{scheduler=$null;folder=$script:fixtureFolder}}
'''


def run_plan(tmp_path, mode='print', capture='', setup=''):
    body = fx.ps_functions(WRAPPER) + "$script:fixtureParent=" + q(tmp_path) + ";$script:runtimeFails=$false\n" + PLAN_PRELUDE + setup + r'''
$sw=[IO.StringWriter]::new();$o=[Console]::Out;[Console]::SetOut($sw)
try{$code=Invoke-AgyLoginMain -Slot 'Slot3' -LoginMode ''' + q(mode) + " -CaptureAttempt " + q(capture) + " -ApplyRequested $false -InteractiveRequested $false -ScriptRoot " + q(W) + r'''}
finally{[Console]::SetOut($o)}
[ordered]@{code=$code;plan=($sw.ToString()|ConvertFrom-Json);pins_opened=$script:pinsOpened}|ConvertTo-Json -Depth 8 -Compress
'''
    return json.loads(fx.ps_run(body))


def test_read_only_plan_shape_with_no_holds(tmp_path):
    result = run_plan(tmp_path, setup="$script:fixtureFolder.Tasks['CoChem-4.2.7-Warden']=New-DaemonTask $false 1 0\n")
    plan = result['plan']
    assert result['code'] == 0 and result['pins_opened'] == 1
    assert plan['schema'] == 'cochem-interactive-agy-login-plan/1' and plan['mode'] == 'READ_ONLY_PLAN' and plan['slot'] == 'slot3'
    assert plan['holds'] == [] and plan['login_mode'] == 'print' and plan['native_arguments'] == ['-p', '/model']
    assert plan['bridge_sha256'] == digest(fx.BRIDGE_PATH) and plan['support_sha256'] == fx.bridge.SUPPORT_SHA256
    assert plan['history_sha256'] == digest(HISTORY) and plan['native_sha256'] == fx.bridge.AGY_SHA256
    assert plan['task_name_pattern'] == 'CoChem-4.2.7-InteractiveAgy-r4-slot3-<nonce>' and plan['task_execution_time_limit'] == 'PT15M'
    assert (plan['wrapper_deadline_minutes'], plan['bridge_login_seconds'], plan['bridge_post_input_seconds']) == (14, 600, 120)
    assert set(plan['exit_codes']) == {'0', '1', '20'} and plan['login_commands_executed'] == plan['tasks_changed'] == 0
    assert plan['install_receipt_sha256'] == '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
    assert plan['login_mode_evidence'] is None and plan['activation_ready'] is False


def test_plan_reports_every_hold_without_changing_anything(tmp_path):
    (tmp_path / ('InteractiveAgy427-r4-slot3-' + 'a' * 32)).mkdir()
    setup = ("$script:runtimeFails=$true;$script:fixtureFolder.Tasks['CoChem-4.2.7-Warden']=New-DaemonTask $true 3 0;"
             "$script:fixtureFolder.Tasks['CoChem-4.2.7-Supervisor']=New-DaemonTask $false 4 1;$script:fixtureFolder.Denied=@('CoChem-4.2.2-Warden')\n")
    result = run_plan(tmp_path, mode='none', setup=setup)
    holds = result['plan']['holds']
    assert result['code'] == 0 and result['plan']['r4_runtime_verified'] is False and result['plan']['native_arguments'] == []
    assert any(h.startswith('r4 stopped runtime is not the reviewed build') for h in holds)
    assert any(h.startswith('Login mode none') for h in holds)
    assert 'Protected daemons must remain stopped and disabled: CoChem-4.2.7-Warden' in holds
    assert 'Protected daemons must remain stopped and disabled: CoChem-4.2.7-Supervisor' in holds
    assert 'Daemon task definition is unreadable without elevation; re-read during -Apply: CoChem-4.2.2-Warden' in holds
    assert any('Earlier agy sessions of this slot' in h for h in holds)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['InteractiveAgy427-r4-slot3-' + 'a' * 32]


@pytest.mark.parametrize('captured,requested,tamper,gate,expected', [
    ('print', 'print', False, True, []),
    ('tui', 'tui', False, True, []),
    ('print', 'tui', False, True, ['-LoginMode tui differs from login-mode.json (print)']),
    ('none', 'none', False, False, ['Login mode none', 'The signed-out capture gate did not pass']),
    ('print', 'print', True, True, ['Signed-out capture evidence: Source digest changed']),
])
def test_plan_binds_login_mode_json_through_the_capture_receipt(tmp_path, captured, requested, tamper, gate, expected):
    attempt = '5' * 32
    capture_fixture(tmp_path, attempt, captured, gate=gate, tamper=tamper)
    result = run_plan(tmp_path, mode=requested, capture=attempt)
    holds = result['plan']['holds']
    assert len(holds) == len(expected) and all(any(h.startswith(prefix) for h in holds) for prefix in expected), holds
    evidence = result['plan']['login_mode_evidence']
    if not tamper:
        assert evidence['mode'] == captured and evidence['capture_attempt'] == attempt and evidence['path'].endswith(r'-slot1-signed-out\login-mode.json')
        assert evidence['sha256'] == hashlib.sha256((Path(evidence['path'])).read_bytes()).hexdigest()


@pytest.mark.parametrize('exit_code,holds', [(0, False), (20, False), (0, True)])
def test_main_apply_branch_returns_exactly_one_exit_value_and_refuses_on_holds(tmp_path, exit_code, holds):
    setup = ("function Get-AgyLoginHostProbe {" + GOOD_PROBE + "}\n$script:applyCalls=0\n"
             "function Invoke-AgyLoginApply {param($Scheduler,$Folder,$Runtime,$Slot,$LoginMode,$Evidence) $script:applyCalls++;"
             "[pscustomobject]@{exit_code=" + str(exit_code) + ";result=[ordered]@{schema='cochem-interactive-agy-login-result/1';slot=$Slot;message='fixture'}}}\n")
    if holds:
        setup += "$script:fixtureFolder.Tasks['CoChem-4.2.7-Warden']=New-DaemonTask $true 3 0\n"
    body = fx.ps_functions(WRAPPER) + "$script:fixtureParent=" + q(tmp_path) + ";$script:runtimeFails=$false\n" + PLAN_PRELUDE + setup + r'''
$hosts=[Collections.Generic.List[string]]::new();function Write-Host {param($Object) $hosts.Add([string]$Object)}
$sw=[IO.StringWriter]::new();$o=[Console]::Out;[Console]::SetOut($sw);$values=$null;$message=$null;$resolved=$null
try{$values=@(Invoke-AgyLoginMain -Slot 'slot2' -LoginMode 'tui' -CaptureAttempt '' -ApplyRequested $true -InteractiveRequested $true -ScriptRoot ''' + q(W) + r''');$resolved=Resolve-AgyLoginExitCode $values}
catch{$message=$_.Exception.Message}finally{[Console]::SetOut($o)}
[ordered]@{values=$values;resolved=$resolved;message=$message;apply_calls=$script:applyCalls;out=$sw.ToString();hosts=@($hosts)}|ConvertTo-Json -Depth 6 -Compress
'''
    result = json.loads(fx.ps_run(body))
    if holds:
        assert result['apply_calls'] == 0 and result['message'].startswith('The agy login is held. Nothing was changed: ')
        assert 'Protected daemons must remain stopped and disabled: CoChem-4.2.7-Warden' in result['message']
    else:
        assert result['apply_calls'] == 1 and result['values'] == [exit_code] and result['resolved'] == exit_code
        assert json.loads(result['out'])['slot'] == 'slot2'
        assert any(line.startswith('COCHEM_AGY_LOGIN_PAUSE slot2') for line in result['hosts']) is (exit_code == 20)


# ----- -Apply body through the real functions with fixture scheduler, receipts and roots -----

APPLY_PRELUDE = r'''
$held=[Collections.Generic.List[IO.FileStream]]::new()
function Assert-NoReparseAncestors {param([string]$Path)}
function Assert-ProtectedPath {param([string]$Path)}
Initialize-FileIdentity
function New-PrivateAcl {param([switch]$Directory)
    if($Directory){$acl=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{$acl=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;$acl.SetAccessRuleProtection($true,$false);$acl.SetOwner($sid)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'));$acl}
$script:codeTrees=@();function Assert-CodeTreeOnce {param([string]$Path) $script:codeTrees+=$Path;1}
$script:historyCalls=@();function Assert-ReviewedAgyHistory {param($Slot,$Folder,$Runtime) $script:historyCalls+=$Slot}
function Get-AgyHistoryExpectedSid {param([string]$Slot) ''' + q(fx.SID) + r'''}
function New-AgyLoginNonce {''' + q(NONCE) + r'''}
$script:hosts=[Collections.Generic.List[string]]::new();function Write-Host {param($Object) $script:hosts.Add([string]$Object)}
$script:runtime=[ordered]@{install_receipt_sha256='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';source_manifest_sha256='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';configuration_sha256='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c';revision=[pscustomobject]@{source_sha256='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'}}
$scheduler=[pscustomobject]@{}
$scheduler|Add-Member ScriptMethod NewTask {param($flags)
    $actions=[pscustomobject]@{List=[Collections.Generic.List[object]]::new()}
    $actions|Add-Member ScriptMethod Create {param($type) $a=[pscustomobject]@{Type=$type;Path=$null;Arguments=$null;WorkingDirectory=$null};$this.List.Add($a);$a}
    $actions|Add-Member ScriptProperty Count {$this.List.Count}
    $actions|Add-Member ScriptMethod Item {param($index)$this.List[$index-1]}
    [pscustomobject]@{RegistrationInfo=[pscustomobject]@{Description=$null};Principal=[pscustomobject]@{UserId=$null;LogonType=$null;RunLevel=$null};
        Settings=[pscustomobject]@{Enabled=$null;AllowDemandStart=$null;MultipleInstances=$null;ExecutionTimeLimit=$null;RestartCount=$null};Actions=$actions;Triggers=[pscustomobject]@{Count=0}}}
$folder=[pscustomobject]@{Tasks=@{};Registered=0}
$folder|Add-Member ScriptMethod GetTask {param($name) if($this.Tasks.ContainsKey($name)){return $this.Tasks[$name]};throw [Runtime.InteropServices.COMException]::new('fixture missing',-2147024894)}
$folder|Add-Member ScriptMethod RegisterTaskDefinition {param($name,$definition,$flags,$user,$password,$logon,$sddl)
    if($flags -ne 2 -or $user -cne 'SYSTEM' -or $null -ne $password -or $logon -ne 5){throw 'fixture registration arguments differ'}
    $this.Registered++
    if($script:sddlOverride){$sddl=$script:sddlOverride}
    $task=[pscustomobject]@{Name=$name;State=3;LastTaskResult=267011;Definition=$definition;Enabled=[bool]$definition.Settings.Enabled;InstanceCount=0;Sddl=$sddl;RunCount=0}
    $task|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=$this.InstanceCount}}
    $task|Add-Member ScriptMethod GetSecurityDescriptor {param($f)$this.Sddl}
    $task|Add-Member ScriptMethod Run {param($p) $this.RunCount++;[pscustomobject]@{fixture=$true}}
    $this.Tasks[$name]=$task;$script:lastTask=$task;$task}
function Invoke-AgyLoginConsoleLoop {param($Instance,[string]$Root,[string]$Nonce,[DateTime]$DeadlineUtc)
    if(-not $Instance.fixture -or $Nonce -cne ''' + q(NONCE) + r''' -or $Root -cne $script:sessionRoot -or $DeadlineUtc -le [DateTime]::UtcNow.AddMinutes(13)){throw 'fixture loop binding lost'}
    if($script:receiptSource){Copy-Item -LiteralPath $script:receiptSource -Destination (Join-Path $Root 'receipt.json')}
    if($null -ne $script:receiptText){[IO.File]::WriteAllText((Join-Path $Root 'receipt.json'),$script:receiptText)}
    # A line written after the bridge left its read loop: never read by the bridge (fixture bytes, not a code).
    if($script:lateInput){[IO.File]::WriteAllBytes((Join-Path $Root 'input.once'),[Text.Encoding]::ASCII.GetBytes("cochem-login-input/1`nfixture`n"))}
    $script:lastTask.LastTaskResult=$script:fixtureLast
    [pscustomobject]@{native_prompt_seen=$true;one_line_submitted=$script:loopWrote;cancel_requested=$false;input_window_closed=$false;code_prompt_held=$false}}
$script:lateInput=$false;$script:loopWrote=$true;$script:receiptText=$null
'''


def apply_fixture(tmp_path, scenario=None, generated=None, mode='print', last=None, setup=''):
    parent = tmp_path / 'CoChem'; parent.mkdir(parents=True, exist_ok=True)
    source = generated[scenario]['root'] / 'receipt.json' if scenario else None
    last = generated[scenario]['code'] if (scenario and last is None) else (last or 0)
    body = (fx.ps_functions(WRAPPER) + fx.ps_functions(HISTORY)
            + ps_named(STAGE, ['Initialize-FileIdentity', 'Open-VerifiedFile']) + ps_named(STATUS, ['Read-R3Control', 'Read-R3Text'])
            + ps_named(V6, ['Get-ExactTaskOrAbsent', 'Assert-TaskTerminal']) + ps_named(REGISTER, ['Assert-RegisteredTaskAcl'])
            + "Set-AgyLoginConstants 'slot3' " + q(mode) + " " + q(W) + "\n$script:cochemRoot=" + q(parent) + "\n"
            + "$script:receiptSource=" + (q(source) if source else '$null') + ";$script:fixtureLast=" + str(last) + ";$script:sddlOverride=$null\n"
            + APPLY_PRELUDE + setup + r'''
$outcome=$null;$message=$null
try{$outcome=Invoke-AgyLoginApply $scheduler $folder $script:runtime 'slot3' ''' + q(mode) + r''' $null}catch{$message=$_.Exception.Message}
foreach($stream in $held){$stream.Dispose()}
$root=$script:sessionRoot;$files=@();$resultRecord=$null;$heldRecord=$null;$task=$null
if($root -and (Test-Path -LiteralPath $root)){
    $files=@(Get-ChildItem -LiteralPath $root -Force|ForEach-Object{$_.Name}|Sort-Object)
    if(Test-Path -LiteralPath (Join-Path $root 'session-result.json')){$resultRecord=Get-Content -LiteralPath (Join-Path $root 'session-result.json') -Raw|ConvertFrom-Json}
    if(Test-Path -LiteralPath (Join-Path $root 'session-held.json')){$heldRecord=Get-Content -LiteralPath (Join-Path $root 'session-held.json') -Raw|ConvertFrom-Json}
}
if($folder.Registered){$t=$script:lastTask;$a=$t.Definition.Actions.Item(1)
    $task=[ordered]@{name=$t.Name;path=$a.Path;arguments=$a.Arguments;working_directory=$a.WorkingDirectory;user=$t.Definition.Principal.UserId;logon=$t.Definition.Principal.LogonType;
        run_level=$t.Definition.Principal.RunLevel;limit=$t.Definition.Settings.ExecutionTimeLimit;instances=$t.Definition.Settings.MultipleInstances;restart=$t.Definition.Settings.RestartCount;
        enabled=$t.Definition.Settings.Enabled;demand=$t.Definition.Settings.AllowDemandStart;runs=$t.RunCount;sddl=$t.Sddl;description=$t.Definition.RegistrationInfo.Description}}
[ordered]@{exit_code=$(if($null -ne $outcome){$outcome.exit_code}else{$null});result=$(if($null -ne $outcome){$outcome.result}else{$null});message=$message;root=$root;files=$files;
    session_result=$resultRecord;session_held=$heldRecord;task=$task;registered=$folder.Registered;code_trees=$script:codeTrees;history_calls=$script:historyCalls;hosts=@($script:hosts)}|ConvertTo-Json -Depth 8 -Compress
''')
    return json.loads(fx.ps_run(body, timeout=120))


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    return fx.receipts(tmp_path_factory.mktemp('agy-wrapper-receipts'))


def test_apply_accepts_exit_zero_writes_session_result_and_registers_the_exact_task(tmp_path, generated):
    result = apply_fixture(tmp_path, 'print_exit_zero', generated)
    assert result['message'] is None and result['exit_code'] == 0
    root = result['root']
    assert root == str(tmp_path / 'CoChem' / f'InteractiveAgy427-r4-slot3-{NONCE}')
    assert result['files'] == ['receipt.json', 'session-result.json', 'worker_agy_login_bridge_r4_v1.py', 'worker_native_status_support.py']
    assert digest(Path(root) / 'worker_agy_login_bridge_r4_v1.py') == digest(fx.BRIDGE_PATH)
    assert digest(Path(root) / 'worker_native_status_support.py') == digest(fx.SUPPORT_PATH)
    task = result['task']
    assert task == {'name': f'CoChem-4.2.7-InteractiveAgy-r4-slot3-{NONCE}', 'path': r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe',
                    'arguments': f'-I -B "{root}\\worker_agy_login_bridge_r4_v1.py" --slot slot3 --nonce {NONCE} --login-mode print',
                    'working_directory': root, 'user': 'SYSTEM', 'logon': 5, 'run_level': 1, 'limit': 'PT15M', 'instances': 2, 'restart': 0,
                    'enabled': True, 'demand': True, 'runs': 1, 'sddl': 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)', 'description': task['description']}
    assert result['code_trees'] == [r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4', r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312',
                                    r'C:\Program Files\CoChem\Native4.2.7-windows-20261006']
    assert result['history_calls'] == ['slot3'] and result['registered'] == 1
    record = result['session_result']
    assert record['schema'] == 'cochem-interactive-agy-login-result/1' and record['status'] == 'LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED'
    assert record['outcome'] == 'LOGIN_ENDED_STATUS_REQUIRED' and record['exit_code'] == 0 and record['authentication_verified'] is False
    assert record['receipt_sha256'] == digest(Path(root) / 'receipt.json') and record['last_task_result'] == 0
    assert record['next_step'] == 'Reviewed native status check: check-worker-native-auth-status-six-r4-v1.ps1 -Slot slot3 -Provider gemini -Stage after'
    assert result['result']['session_record_sha256'] == digest(Path(root) / 'session-result.json')
    assert any('Gemini (agy) Google sign-in for slot3 in print mode.' == line for line in result['hosts'])


@pytest.mark.parametrize('scenario,mode,exit_code,outcome', [
    ('tui_terminated', 'tui', 0, 'LOGIN_ENDED_STATUS_REQUIRED'),
    ('callback_exit_zero', 'print', 0, 'LOGIN_ENDED_STATUS_REQUIRED'),
    ('rate_limited', 'print', 20, 'PAUSED_RATE_LIMIT_OR_IDENTITY_VERIFICATION'),
    ('verify_cancelled', 'print', 20, 'PAUSED_RATE_LIMIT_OR_IDENTITY_VERIFICATION'),
])
def test_apply_exit_codes_for_accepted_and_paused_sessions(tmp_path, generated, scenario, mode, exit_code, outcome):
    result = apply_fixture(tmp_path, scenario, generated, mode=mode)
    assert result['message'] is None and result['exit_code'] == exit_code
    assert result['session_result']['outcome'] == outcome and result['session_held'] is None
    assert result['session_result']['pause_marker_seen'] is (exit_code == 20)
    text = json.dumps(result)
    assert fx.CODE.decode() not in text and fx.EMAIL not in text


@pytest.mark.parametrize('scenario,fragment', [
    ('fail_before_input', 'agy refused interactive sign-in without a controlling terminal'),
    ('fail_after_input', 'markers: authentication_failed_present'),
    ('cancelled', 'The agy sign-in was cancelled at the console'),
    ('timed_out', 'No authorization code was submitted within 600 s'),
    ('native_custody_failure', 'The login bridge refused before launching agy'),
    ('output_bound', 'agy printed more display text than the 131072-byte bound before any code was submitted'),
    ('cleanup_unverified', 'Historical agy receipt requires diagnosis'),
    ('agy_changed_after', 'Historical agy receipt requires diagnosis'),
])
def test_apply_failures_throw_and_leave_a_created_new_held_record(tmp_path, generated, scenario, fragment):
    mode = fx.SCENARIOS[scenario]['mode']
    result = apply_fixture(tmp_path, scenario, generated, mode=mode)
    assert result['exit_code'] is None and fragment in result['message'] and 'Gemini stays held for this slot' in result['message']
    held = result['session_held']
    assert held['schema'] == 'cochem-interactive-agy-login-held/1' and held['phase'] == 'DECISION' and result['session_result'] is None
    assert held['receipt_present'] is True and held['receipt_sha256'] == digest(Path(result['root']) / 'receipt.json')
    assert held['code_recorded'] is False and held['automatic_retry_allowed'] is False and held['requires_owner_review'] is True
    if scenario in ('cleanup_unverified', 'agy_changed_after'):
        assert held['receipt_proof'] is None and held['receipt_metadata']['status'] in ('CLEANUP_UNVERIFIED', 'LOGIN_FAILED_OR_CANCELLED')
    else:
        assert held['receipt_proof']['classification'] and held['receipt_metadata'] is None
    text = json.dumps(result)
    assert fx.CODE.decode() not in text and fx.EMAIL not in text and 'https://' not in text


FED = 'The receipt shows the bridge fed the one line to agy.'
NOT_FED = 'The receipt shows the bridge never read the line, so agy did not receive it'


@pytest.mark.parametrize('scenario,receipt_text,last,phase', [
    ('timed_out', None, None, 'DECISION'),          # TimeoutError receipt: one_line_submitted false
    (None, None, 3, 'RECEIPT'),                     # no receipt at all: the bridge never reached its read loop
])
def test_apply_deletes_an_unread_input_after_the_task_ended_and_says_so(tmp_path, generated, scenario, receipt_text, last, phase):
    """O-F6: a line written after the bridge's window closed is deleted once the task ended; the console matches the receipt."""
    mode = fx.SCENARIOS[scenario]['mode'] if scenario else 'print'
    result = apply_fixture(tmp_path, scenario, generated, mode=mode, last=last, setup='$script:lateInput=$true\n')
    held = result['session_held']
    assert result['exit_code'] is None and held['phase'] == phase and 'input.once' not in result['files']
    assert held['input_cleanup'] == {'input_present': True, 'consumed': False, 'deleted': True}
    if scenario:
        assert any(line.startswith(NOT_FED) and 'deleted' in line for line in result['hosts'])
        assert not any(line == FED for line in result['hosts'])


def test_apply_keeps_a_consumed_or_unprovable_input_for_the_bridge_rules(tmp_path, generated):
    consumed = apply_fixture(tmp_path / 'consumed', 'print_exit_zero', generated, setup='$script:lateInput=$true\n')
    assert consumed['exit_code'] == 0 and 'input.once' in consumed['files']
    assert consumed['session_result']['input_cleanup'] == {'input_present': True, 'consumed': True, 'deleted': False}
    assert FED in consumed['hosts'] and not any(line.startswith(NOT_FED) for line in consumed['hosts'])
    unreadable = apply_fixture(tmp_path / 'unreadable', None, generated, last=2, setup="$script:lateInput=$true;$script:receiptText=''\n")
    assert unreadable['exit_code'] is None and 'input.once' in unreadable['files']
    assert unreadable['session_held']['input_cleanup'] == {'input_present': True, 'consumed': None, 'deleted': False}
    clean = apply_fixture(tmp_path / 'clean', 'print_exit_zero', generated)
    assert clean['session_result']['input_cleanup'] == {'input_present': False, 'consumed': None, 'deleted': False}


def test_apply_without_a_receipt_and_with_a_wrong_task_acl_holds(tmp_path, generated):
    missing = apply_fixture(tmp_path / 'missing', None, generated, last=3)
    assert 'The login bridge left no receipt (LastTaskResult 3)' in missing['message'] and missing['session_held']['phase'] == 'RECEIPT'
    acl = apply_fixture(tmp_path / 'acl', 'print_exit_zero', generated, setup="$script:sddlOverride='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;WD)'\n")
    assert acl['exit_code'] is None and acl['session_held']['phase'] == 'REGISTER' and acl['task']['runs'] == 0
    assert acl['files'] == ['session-held.json', 'worker_agy_login_bridge_r4_v1.py', 'worker_native_status_support.py']


def test_apply_refuses_an_existing_root_or_task_before_creating_anything(tmp_path, generated):
    root = tmp_path / 'root' / 'CoChem' / f'InteractiveAgy427-r4-slot3-{NONCE}'
    root.mkdir(parents=True)
    existing_root = apply_fixture(tmp_path / 'root', 'print_exit_zero', generated)
    assert existing_root['message'] == 'Fresh login root unexpectedly exists. Nothing was changed.' and existing_root['files'] == []
    existing_task = apply_fixture(tmp_path / 'task', 'print_exit_zero', generated,
                                  setup="$folder.Tasks['CoChem-4.2.7-InteractiveAgy-r4-slot3-" + NONCE + "']=[pscustomobject]@{Name='x'}\n")
    assert existing_task['message'] == 'Fresh login task unexpectedly exists. Nothing was changed.'
    assert existing_task['registered'] == 0 and not (tmp_path / 'task' / 'CoChem' / f'InteractiveAgy427-r4-slot3-{NONCE}').exists()


def test_apply_mode_must_match_the_receipt(tmp_path, generated):
    result = apply_fixture(tmp_path, 'print_exit_zero', generated, mode='tui')
    assert result['exit_code'] is None and 'Historical agy receipt requires diagnosis' in result['message']


# ----- records, copies, outcome mapping and exit codes -----

RECORD_PRELUDE = r'''
function New-PrivateAcl {param([switch]$Directory) $acl=[Security.AccessControl.FileSecurity]::new();$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;$acl.SetAccessRuleProtection($true,$false);$acl.SetOwner($sid);$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow'));$acl}
'''


def test_session_record_is_created_new_bounded_and_private(tmp_path):
    path = tmp_path / 'session-result.json'
    body = fx.ps_functions(WRAPPER) + RECORD_PRELUDE + "Set-AgyLoginConstants 'slot3' 'print' " + q(W) + "\n$path=" + q(path) + r'''
$sha=Write-AgySessionRecord $path ([ordered]@{schema='fixture';value=1})
$second=$null;try{$null=Write-AgySessionRecord $path ([ordered]@{schema='other'})}catch{$second=$_.Exception.GetType().Name}
$big=$null;try{$null=Write-AgySessionRecord ($path+'.big') ([ordered]@{value=('x'*70000)})}catch{$big=$_.Exception.Message}
$acl=Get-Acl -LiteralPath $path
[ordered]@{sha=$sha;second=$second;big=$big;big_exists=(Test-Path -LiteralPath ($path+'.big'));protected=$acl.AreAccessRulesProtected;rules=@($acl.Access).Count}|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    assert result['sha'] == digest(path) and json.loads(path.read_text())['schema'] == 'fixture'
    assert result['second'] in ('IOException', 'MethodInvocationException') and result['big'] == 'Session record exceeds its bound.'
    assert result['big_exists'] is False and result['protected'] is True and result['rules'] == 1


def test_session_sources_are_copied_create_new_and_verified(tmp_path):
    body = (fx.ps_functions(WRAPPER) + RECORD_PRELUDE + ps_named(STAGE, ['Initialize-FileIdentity', 'Open-VerifiedFile'])
            + "function Assert-NoReparseAncestors {param([string]$Path)}\nInitialize-FileIdentity\n$held=[Collections.Generic.List[IO.FileStream]]::new()\n"
            + "Set-AgyLoginConstants 'slot3' 'print' " + q(W) + "\n$script:sessionRoot=" + q(tmp_path) + r'''
Copy-AgySessionSources;$first=$held.Count
$again=$null;try{Copy-AgySessionSources}catch{$again='REFUSED'}
foreach($s in $held){$s.Dispose()}
[ordered]@{held=$first;again=$again}|ConvertTo-Json -Compress
''')
    result = json.loads(fx.ps_run(body))
    assert result == {'held': 2, 'again': 'REFUSED'}
    assert digest(tmp_path / 'worker_agy_login_bridge_r4_v1.py') == digest(fx.BRIDGE_PATH)
    assert digest(tmp_path / 'worker_native_status_support.py') == fx.bridge.SUPPORT_SHA256


def test_outcome_mapping_table():
    body = fx.ps_functions(WRAPPER) + "Set-AgyLoginConstants 'slot3' 'print' " + q(W) + "\n" + r'''
function P($c,$a,$p,$clean=$true,$code=0,[string[]]$markers=@()){[pscustomobject]@{classification=$c;accepted=$a;pause_marker_seen=$p;cleanup_verified=$clean;native_exit_code=$code;failure_markers=$markers}}
$native='TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED'
$cases=[ordered]@{
  accepted=(P $native $true $false);accepted_pause=(P $native $true $true);failed=(P $native $false $false -code 1);failed_pause=(P $native $false $true -code 1)
  cancelled_pause=(P 'TERMINAL_CANCELLED_NATIVE_LOGIN_CLEANUP_VERIFIED' $false $true);timed_out=(P 'TERMINAL_TIMED_OUT_NATIVE_LOGIN_CLEANUP_VERIFIED' $false $false)
  custody_pause=(P 'TERMINAL_PRE_NATIVE_CUSTODY_FAILURE_NO_CHILD_LAUNCHED' $false $true -clean $false);accepted_unclean=(P $native $true $false -clean $false)
  accepted_string=(P $native 'true' $false);nct=(P $native $false $false -code 1 -markers @('no_controlling_terminal_present','authentication_required_present'))
  clean_string=(P $native $true $false -clean 'true')
  output_bound=(P 'TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED' $false $false);output_bound_pause=(P 'TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED' $false $true)
}
$out=[ordered]@{};foreach($k in $cases.Keys){$o=Get-AgyLoginOutcome $cases[$k];$out[$k]=[ordered]@{code=$o.exit_code;outcome=$o.outcome;message=$o.message}}
$out|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    codes = {name: value['code'] for name, value in result.items()}
    assert codes == {'accepted': 0, 'accepted_pause': 20, 'failed': None, 'failed_pause': 20, 'cancelled_pause': 20, 'timed_out': None,
                     'custody_pause': None, 'accepted_unclean': None, 'accepted_string': None, 'nct': None, 'clean_string': None,
                     'output_bound': None, 'output_bound_pause': 20}
    assert result['output_bound']['outcome'] == 'LOGIN_NOT_COMPLETED' and 'a fresh attempt is not blocked' in result['output_bound']['message']
    assert result['nct']['message'] == ('The agy sign-in command ended with exit code 1 (agy refused interactive sign-in without a controlling '
                                        'terminal); cleanup is verified.')


def test_exit_code_resolution_table():
    body = fx.ps_functions(WRAPPER) + r'''
$out=[ordered]@{}
foreach($case in @(@('zero',@(0)),@('pause',@(20)),@('one',@(1)),@('empty',@()),@('two',@(0,0)),@('string',@('0')),@('long',@([long]0)))){
    try{$out[$case[0]]=Resolve-AgyLoginExitCode $case[1]}catch{$out[$case[0]]='REFUSED'}
}
$out|ConvertTo-Json -Compress
'''
    assert json.loads(fx.ps_run(body)) == {'zero': 0, 'pause': 20, 'one': 'REFUSED', 'empty': 'REFUSED', 'two': 'REFUSED',
                                           'string': 'REFUSED', 'long': 'REFUSED'}


def test_daemon_holds_cover_the_four_names_only():
    body = fx.ps_functions(WRAPPER) + "Set-AgyLoginConstants 'slot3' 'print' " + q(W) + "\n" + r'''
function New-DaemonTask($Enabled,$State,$Instances){$t=[pscustomobject]@{Enabled=$Enabled;State=$State;InstanceCount=$Instances};$t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=$this.InstanceCount}};$t}
$folder=[pscustomobject]@{Tasks=@{'CoChem-4.2.7-Warden'=(New-DaemonTask $false 1 0);'CoChem-4.2.7-Supervisor'=(New-DaemonTask $false 3 1);'CoChem-4.2.7-Observer'=(New-DaemonTask $true 4 1)};Asked=[Collections.Generic.List[string]]::new()}
$folder|Add-Member ScriptMethod GetTask {param($name) $this.Asked.Add($name);if($this.Tasks.ContainsKey($name)){return $this.Tasks[$name]};if($name -ceq 'CoChem-4.2.3-Supervisor'){throw [Runtime.InteropServices.COMException]::new('odd',-2147467259)};throw [Runtime.InteropServices.COMException]::new('missing',-2147024894)}
[ordered]@{holds=@(Get-AgyDaemonHolds $folder);asked=@($folder.Asked)}|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    assert result['asked'] == ['CoChem-4.2.7-Warden', 'CoChem-4.2.7-Supervisor', 'CoChem-4.2.2-Warden', 'CoChem-4.2.3-Supervisor']
    assert result['holds'] == ['Protected daemons must remain stopped and disabled: CoChem-4.2.7-Supervisor',
                               'Daemon task state is unknown: CoChem-4.2.3-Supervisor']


# ----- pins, imports and source shape -----

PIN_FILES = {
    'bridgeHash': W / 'worker_agy_login_bridge_r4_v1.py', 'supportHash': W / 'worker-native-auth-status-six-r4-v1.py',
    'copyHelperHash': STAGE, 'statusFunctionsHash': STATUS, 'leafFunctionsHash': W / 'check-worker-native-auth-status-six-r4-v1.ps1',
    'registrationFunctionsHash': REGISTER, 'inspectionFunctionsHash': W / 'protected-code-inspection-v4.ps1', 'codeInputHash': INPUT,
    'v6LeafHash': V6, 'historyHash': HISTORY,
}


def test_every_embedded_helper_pin_is_recomputed_from_disk():
    text = WRAPPER.read_text()
    for name, path in PIN_FILES.items():
        match = re.search(r"\$script:" + name + r"='([a-f0-9]{64})'", text)
        assert match and match.group(1) == digest(path), name


def test_real_pinned_imports_parse_and_provide_every_required_function():
    body = fx.ps_functions(WRAPPER) + "Set-AgyLoginConstants 'slot3' 'print' " + q(W) + "\n" + r'''
$definitions=@(Get-AgyLoginHelperDefinitions)
$names=@($definitions|ForEach-Object{([regex]::Match($_,'\Afunction\s+([A-Za-z0-9-]+)')).Groups[1].Value})
[ordered]@{count=$definitions.Count;names=$names}|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    assert result['count'] == 39 and len(set(result['names'])) == 39
    for name in ('Assert-R4InstalledBindings', 'Assert-VenvBinding', 'Write-PrivatePacket', 'Write-CancelRequest', 'Test-InstanceComplete',
                 'Clear-ClaudeConsoleInput', 'Update-ClaudeCodeInput', 'Assert-ReviewedAgyHistory', 'Assert-AgyHistoryReceipt',
                 'Assert-RegisteredTaskAcl', 'Assert-CodeTreeOnce', 'Read-R3Control', 'Open-VerifiedFile'):
        assert name in result['names'], name


def test_wrapper_shape_single_invocation_and_input_handling_order():
    body = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile(" + q(WRAPPER) + ",[ref]$t,[ref]$e);"
            "[ordered]@{errors=$e.Count;params=@($a.ParamBlock.Parameters|ForEach-Object{$_.Name.VariablePath.UserPath});"
            "statements=@($a.EndBlock.Statements|ForEach-Object{$_.GetType().Name});last=$a.EndBlock.Statements[-1].Extent.Text}|ConvertTo-Json -Compress")
    shape = json.loads(fx.ps_run(body))
    assert shape['errors'] == 0 and shape['params'] == ['Slot', 'LoginMode', 'Apply', 'Interactive', 'CaptureAttempt']
    assert shape['statements'][:-1] == ['FunctionDefinitionAst'] * (len(shape['statements']) - 1)
    assert shape['statements'][-1] == 'ExitStatementAst' and shape['last'].startswith('exit (Resolve-AgyLoginExitCode @(Invoke-AgyLoginMain ')
    text = WRAPPER.read_text()
    text.encode('ascii')
    assert 'Read-Host' not in text and '[Console]::ReadKey($true).Key' not in text
    loop = text[text.index('function Invoke-AgyLoginConsoleLoop'):text.index('function Get-AgyLoginFailureMessage')]
    branch = loop[loop.index('$inputState.SubmissionRequested -and -not $inputState.Submitted'):]
    # O-F6: the closed marker and the task end are checked immediately before the one packet write.
    assert branch.index('if((Test-Path -LiteralPath $closedPath) -or (Test-InstanceComplete $Instance))') < branch.index('Write-PrivatePacket $inputPath') \
        < branch.index('Complete-ClaudeCodeInput -State $inputState')
    assert "$closedPath=Join-Path $Root 'input.closed'" in loop and "$inputPath=Join-Path $Root 'input.once'" in loop
    assert loop.count('console_queue_clear -isnot [bool]') == 3 and 'Close-ClaudeCodeInput -State $inputState' in loop
    # O-F9: the masked prompt is gated on a Google sign-in URL that precedes the native prompt.
    assert '$readyAt=Find-AgyCodePrompt $text' in loop and "'https://accounts.google.com/'" in text
    assert "[ValidateSet('print','tui','none')][string]$LoginMode" in text


# ----- top level, plan mode only (ps_toplevel_smoke.py) -----
# The only place the wrapper runs as a script: the REAL top level (param block, binding, exit mapping) with the host
# stubbed by ps_toplevel_smoke, which refuses -Apply. That is the 2026-10-11 17:22 failure class (a script parameter
# variable keeps its [Validate*] attributes for the whole run), invisible to the AST fixtures above.
SMOKE_ATTEMPT = '0123456789abcdef0123456789abcdef'
SMOKE_PLAN_SCHEMA = 'cochem-interactive-agy-login-plan/1'


def test_no_assignment_writes_a_validated_parameter_variable():
    body = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile(" + q(WRAPPER) + ",[ref]$t,[ref]$e);if($e.Count){throw $e[0]};"
            "$v=@{};foreach($p in @($a.ParamBlock.Parameters)){if(@($p.Attributes|Where-Object{$_.TypeName.Name -like 'Validate*'}).Count){$v[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=1}};"
            "$hits=@(foreach($n in $a.FindAll({param($x)$x -is [Management.Automation.Language.AssignmentStatementAst]},$true)){"
            "$targets=@($n.Left);if($n.Left -is [Management.Automation.Language.ArrayLiteralAst]){$targets=@($n.Left.Elements)};"
            "foreach($l in $targets){if($l -is [Management.Automation.Language.ConvertExpressionAst]){$l=$l.Child};if($l -isnot [Management.Automation.Language.VariableExpressionAst]){continue};"
            "$name=($l.VariablePath.UserPath -replace '^(script|global|local|private):','').ToLowerInvariant();"
            "$f=$n.Parent;while($null -ne $f -and $f -isnot [Management.Automation.Language.FunctionDefinitionAst]){$f=$f.Parent};"
            "if($v.ContainsKey($name) -and ($l.VariablePath.IsScript -or $l.VariablePath.IsGlobal -or $null -eq $f)){$l.Extent.Text+'='+$n.Right.Extent.Text}}});"
            "$sv=@($a.FindAll({param($x)$x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -in @('Set-Variable','New-Variable','sv','nv')},$true)).Count;"
            "'RESULT '+(@{validated=@($v.Keys|Sort-Object);hits=@($hits);set_variable=$sv}|ConvertTo-Json -Compress)")
    output = fx.ps_run(body)
    value = json.loads(next(line for line in output.splitlines() if line.startswith('RESULT '))[len('RESULT '):])
    assert value['validated'] == ['captureattempt', 'loginmode', 'slot']
    # Nothing writes them. Note that -CaptureAttempt's default '' fails its own pattern: harmless while unassigned (defaults
    # are not validated), but a future $script:CaptureAttempt= line would throw for every call without -CaptureAttempt.
    assert value['hits'] == [] and value['set_variable'] == 0


@pytest.mark.parametrize('invocation', ['file', 'command'])
@pytest.mark.parametrize('slot,mode', [('slot1', 'print'), ('slot4', 'tui'), ('slot6', 'print')])
def test_toplevel_plan_for_the_drivers_documented_call(slot, mode, invocation):
    # login-six-workers-status-first-r4-v1.ps1 Invoke-AgyBridgeLogin (S6): -Slot -LoginMode -CaptureAttempt -Apply -Interactive.
    args = ['-Slot', slot, '-LoginMode', mode, '-CaptureAttempt', SMOKE_ATTEMPT, '-Interactive']
    result = smoke.run_toplevel(WRAPPER, args, invocation=invocation)
    assert smoke.plan_mode_outcome(result, plan_schema=SMOKE_PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    assert plan['slot'] == slot and plan['login_mode'] == mode and plan['login_commands_executed'] == 0 and plan['tasks_changed'] == 0
    assert plan['native_arguments'] == (['-p', '/model'] if mode == 'print' else []) and isinstance(plan['holds'], list)


def test_toplevel_plan_without_capture_attempt_keeps_the_unvalidated_default():
    result = smoke.run_toplevel(WRAPPER, ['-Slot', 'slot2', '-LoginMode', 'tui'])
    assert smoke.plan_mode_outcome(result, plan_schema=SMOKE_PLAN_SCHEMA) == 'plan', result.describe()
    assert result.plan['slot'] == 'slot2' and result.plan['login_mode_evidence'] is None
