import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture,'SCRIPT',Path(__file__).parents[1]/'scripts/verify_r6_auth_recovery.ps1')
    return ps_fixture.run_ps


@pytest.mark.parametrize('mutation', ['', 'duplicate','success_changed','agy_changed','cleanup','count'])
def test_recovery_requires_exact_owner_reviewed_eighteen_statuses(run_ps, mutation):
    checks=[dict(worker=f'slot{i}',provider=p,authenticated=p!='gemini',
        status='STATUS_UNVERIFIED' if p=='gemini' else 'REUSE_VERIFIED_SESSION',
        exit_code=1 if p=='gemini' else 0,cleanup_verified=True)
        for i in range(1,7) for p in ('codex','claude','gemini')]
    if mutation=='duplicate': checks[-1]=checks[2]
    if mutation=='success_changed':checks[0]['authenticated']=False
    if mutation=='agy_changed':checks[2]['exit_code']=2
    if mutation=='cleanup':checks[0]['cleanup_verified']=False
    if mutation=='count':checks.pop()
    value=dict(schema='cochem-r6-authentication/1',status='ATTENDED_AUTH_REVIEW_REQUIRED',checks=checks,
        native_model_jobs_executed=0,credentials_copied=False)
    result=run_ps("$value='"+json.dumps(value)+"'|ConvertFrom-Json\n"+r'''
$held=$false
try{Assert-R6AuthRecoveryRows $value}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held'] is bool(mutation)
