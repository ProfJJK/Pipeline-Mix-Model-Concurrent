import hashlib
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture,'SCRIPT',Path(__file__).parents[1]/'scripts/r6_attended_agy.ps1')
    return ps_fixture.run_ps


def test_attended_adapter_clamps_console_input_to_owner_deadline(run_ps,tmp_path):
    # Every imported function is inert. No task, process, OAuth or profile access.
    wrapper=tmp_path/'login_pipeline_worker_agy_terminal.ps1'
    wrapper.write_text(r"""
function Invoke-AgyTerminalMain {param($Slot,$DeadlineText,$LegacyHash,$ApplyRequested,$Directory)
 $script:observedDeadline=[DateTime]::ParseExact($DeadlineText,'o',[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind);$script:observedSlot=$Slot;$script:observedApply=$ApplyRequested
 $script:observedLegacy=$LegacyHash;$script:observedDirectory=$Directory}
""",encoding='utf-8')
    pin=hashlib.sha256(wrapper.read_bytes()).hexdigest()
    result=run_ps(f"""
$expected=[DateTime]::UtcNow.AddMinutes(2)
$code=Invoke-R6AttendedAgy 'slot1' $expected.ToString('o') ('a'*64) $false '{str(tmp_path).replace("'","''")}' '{pin}'
@{{code=$code;same=($script:observedDeadline -eq $expected);legacy=$script:observedLegacy;slot=$script:observedSlot;apply=$script:observedApply;directory=$script:observedDirectory}}|ConvertTo-Json -Compress
""")
    assert result==dict(code=0,same=True,legacy='a'*64,slot='slot1',apply=False,directory=str(tmp_path))


@pytest.mark.parametrize('minutes',[-1,21])
def test_expired_or_unbounded_login_window_refuses_before_any_import(run_ps,minutes):
    result=run_ps(f"""
$held=$false
try{{Invoke-R6AttendedAgy 'slot2' ([DateTime]::UtcNow.AddMinutes({minutes}).ToString('o')) ('a'*64) $false 'C:\fixture' ('b'*64)}}catch{{$held=$true;$message=$_.Exception.Message}}
@{{held=$held;message=$message}}|ConvertTo-Json -Compress
""")
    assert result['held'] and 'window is closed or invalid' in result['message']
