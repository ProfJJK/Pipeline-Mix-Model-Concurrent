import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('r6_launch_packager',Path(__file__).parents[1]/'scripts/prepare_r6_launch_package.py')
packager=importlib.util.module_from_spec(spec);spec.loader.exec_module(packager)


def fixture(tmp_path):
    repo=tmp_path/'repository';scripts=repo/'scripts';scripts.mkdir(parents=True)
    mirror=repo/'docs/deployment/windows-deployment-next';mirror.mkdir(parents=True)
    lines=[]
    for n in range(30):
        name=f'helper-{n}.ps1';data=f'# inert fixture {n}'.encode()
        (mirror/name).write_bytes(data)
        lines.append(f"'{name}'='{hashlib.sha256(data).hexdigest()}'")
    (mirror/'RUN_427_R5_SITTING.ps1').write_text('\n'.join(lines),encoding='utf-8')
    for name in packager.NEW_SCRIPTS:(scripts/name).write_text('# inert fixture',encoding='utf-8')
    (repo/'src/cochem_pipeline').mkdir(parents=True)
    (repo/'src/cochem_pipeline/attended_agy_terminal.py').write_text('# inert fixture')
    bundle=tmp_path/'bundle';bundle.mkdir()
    (bundle/'pipeline.json').write_bytes(b'{}')
    (bundle/'install-manifest.json').write_bytes(b'{}')
    (bundle/'bundle-prepared.json').write_text(json.dumps(dict(status='STOPPED_INSTALL_INPUTS_VERIFIED',
        manifest_sha256=hashlib.sha256(b'{}').hexdigest(),candidate_sha256=hashlib.sha256(b'{}').hexdigest(),source_commit='a'*40)))
    return repo,bundle


def test_packaging_binds_every_input_but_does_not_claim_host_acceptance(tmp_path):
    repo,bundle=fixture(tmp_path);dest=tmp_path/'launch'
    result=packager.prepare(repo,bundle,dest)
    assert result['status']=='LAUNCH_INPUTS_ASSEMBLED'
    assert not result['host_acceptance_executed'] and not result['reviewed_for_owner_execution']
    assert result['launch_manifest_sha256']==hashlib.sha256((dest/'launch-manifest.json').read_bytes()).hexdigest()
    manifest=json.loads((dest/'launch-manifest.json').read_text())
    for row in manifest['scripts']:
        assert row['sha256']==hashlib.sha256((dest/row['name']).read_bytes()).hexdigest()
    assert '-Apply' in result['owner_command']


@pytest.mark.parametrize('change',['child','candidate','collision'])
def test_packaging_refuses_drift_and_never_overwrites_a_previous_package(tmp_path,change):
    repo,bundle=fixture(tmp_path);dest=tmp_path/'launch'
    if change=='child':(repo/'docs/deployment/windows-deployment-next/helper-3.ps1').write_text('changed')
    if change=='candidate':(bundle/'pipeline.json').write_text('changed')
    if change=='collision':dest.mkdir();(dest/'keep').write_text('keep')
    with pytest.raises(ValueError):packager.prepare(repo,bundle,dest)
    if change=='collision':assert (dest/'keep').read_text()=='keep'
    else:assert not dest.exists()


def test_exact_packaged_entry_plan_runs_without_host_actions_and_rejects_changed_child(tmp_path):
    repo,bundle=fixture(tmp_path);dest=tmp_path/'launch'
    source=Path(__file__).parents[1]/'scripts/run_r6_launch.ps1'
    (repo/'scripts/run_r6_launch.ps1').write_bytes(source.read_bytes())
    receipt=packager.prepare(repo,bundle,dest)
    command=[r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
        '-NoProfile','-NonInteractive','-File',str(dest/'run_r6_launch.ps1'),
        '-LaunchManifest',str(dest/'launch-manifest.json'),
        '-LaunchManifestSha256',receipt['launch_manifest_sha256']]
    result=subprocess.run(command,capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    plan=json.loads(result.stdout)
    assert plan['status']=='R6_LAUNCH_PLAN'
    assert not plan['installation_and_host_acceptance_executed']
    (dest/'helper-3.ps1').write_text('changed')
    refused=subprocess.run(command,capture_output=True,timeout=20)
    assert refused.returncode!=0
    assert b'Launch input differs' in refused.stderr
