"""Copy reviewed launch inputs to a fresh ordinary folder; never execute them."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

NEW_SCRIPTS = (
    'run_r6_launch.ps1', 'install_r6_runtime.ps1', 'run_r6_system_phase.ps1',
    'activate_r6_runtime.ps1', 'r6_retarget_core.ps1', 'r6_attended_agy.ps1',
    'stage_aetherdesk_427_payloads.ps1',
    'login_pipeline_worker_agy_terminal.ps1', 'worker_agy_terminal_bridge.py',
)


def read_regular(path, maximum=16777216):
    path=Path(path)
    for part in (path,*path.parents):
        info=part.lstat()
        if part.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Launch packaging cannot follow redirected inputs')
    info=path.stat()
    if not path.is_file() or info.st_nlink != 1 or not 0 <= info.st_size <= maximum:
        raise ValueError('Launch input has alternate links or exceeds bounds')
    data=path.read_bytes()
    if len(data)!=info.st_size: raise ValueError('Launch input changed during preparation')
    return data


def prepare(repository, bundle, destination, auth_recovery=False, verified_continuation=False, custody_continuation=False):
    repository,bundle,destination=map(Path,(repository,bundle,destination))
    if destination.exists() or not destination.is_absolute() or re.search(r'(?i)[\\/](gdrive|google drive)[\\/]',str(destination)):
        raise ValueError('Use a fresh ordinary launch folder outside Google Drive')
    receipt=json.loads(read_regular(bundle/'bundle-prepared.json'))
    manifest_bytes=read_regular(bundle/'install-manifest.json')
    digest=lambda data:hashlib.sha256(data).hexdigest()
    if (receipt.get('status')!='STOPPED_INSTALL_INPUTS_VERIFIED'
        or receipt.get('manifest_sha256')!=digest(manifest_bytes)
        or receipt.get('candidate_sha256')!=digest(read_regular(bundle/'pipeline.json'))):
        raise ValueError('Stopped installation inputs are not bound')
    if auth_recovery and (receipt['manifest_sha256'] != 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4'
            or receipt['candidate_sha256'] != 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'):
        raise ValueError('Recovery is bound to the already installed R6 release')
    mirror=repository/'docs/deployment/windows-deployment-next'
    inputs={p.name:read_regular(p) for p in sorted(mirror.iterdir()) if p.is_file()}
    for name in NEW_SCRIPTS: inputs[name]=read_regular(repository/'scripts'/name)
    inputs['attended_agy_terminal.py']=read_regular(repository/'src/cochem_pipeline/attended_agy_terminal.py')
    if auth_recovery:
        for name in ('r6_auth_recovery.py', 'verify_r6_auth_recovery.ps1'):
            inputs[name]=read_regular(repository/'scripts'/name)
    if verified_continuation:
        if not auth_recovery:
            raise ValueError('Verified continuation reuses the installed R6')
        for name in ('r6_native_retirement.py', 'r6_retirement_guard.py'):
            inputs[name]=read_regular(repository/'scripts'/name)
    if custody_continuation:
        if not verified_continuation:
            raise ValueError('Custody continuation requires the signed-in, immutable R6')
        inputs['r6_custody_amendment.py']=read_regular(repository/'scripts/r6_custody_amendment.py')
    if not 10 <= len(inputs) <= 1024 or sum(map(len,inputs.values()))>128*1024**2:
        raise ValueError('Launch input inventory exceeds bounds')
    for name in inputs:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',name): raise ValueError('Unsafe launch input name')
    # Keep the released R5 dependency graph intact. Loading its definitions is
    # safe; the new entry point never invokes its old deployment series.
    runner=inputs['RUN_427_R5_SITTING.ps1'].decode('utf-8-sig')
    pins=re.findall(r"^\s*'([^']+)'='([a-f0-9]{64})'\s*$",runner,re.M)
    if len(pins)<30: raise ValueError('Released dependency pin table was not found')
    for name,pin in pins:
        if name not in inputs or digest(inputs[name])!=pin:
            raise ValueError('Released dependency differs: '+name)
    destination.mkdir(parents=False)
    rows=[]
    for name,data in sorted(inputs.items()):
        with (destination/name).open('xb') as out: out.write(data)
        rows.append(dict(name=name,length=len(data),sha256=digest(data)))
    launch=dict(schema='cochem-r6-launch-package/1',host='AETHERDESK',source_commit=receipt['source_commit'],
        install_manifest=str((bundle/'install-manifest.json').absolute()),manifest_sha256=receipt['manifest_sha256'],
        candidate_sha256=receipt['candidate_sha256'],scripts=rows,
        user_input_window_minutes=20,late_prompts=False,installation_and_host_acceptance_executed=False)
    if auth_recovery:
        launch['auth_recovery']='20261012-first-auth-hold'
    if verified_continuation:
        launch['verified_signin_continuation']='20261013-six-agy-verified-r4-v7'
    if custody_continuation:
        launch['agent_custody_continuation']='20261013-reviewed-agent-hold-r4-v8'
    data=(json.dumps(launch,indent=2)+'\n').encode()
    with (destination/'launch-manifest.json').open('xb') as out:out.write(data)
    launch_hash=digest(data)
    command=(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File '
        f'"{destination / "run_r6_launch.ps1"}" -LaunchManifest "{destination / "launch-manifest.json"}" '
        f'-LaunchManifestSha256 {launch_hash} -Apply')
    result=dict(schema='cochem-r6-launch-preparation/1',status='LAUNCH_INPUTS_ASSEMBLED',
        source_commit=receipt['source_commit'],launch_manifest_sha256=launch_hash,scripts=len(rows),
        owner_command=command,host_acceptance_executed=False,activation_ready=False,
        reviewed_for_owner_execution=False)
    with (destination/'launch-prepared.json').open('x',encoding='utf-8',newline='\n') as out:
        json.dump(result,out,indent=2)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('repository','bundle','destination'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--auth-recovery', action='store_true')
    parser.add_argument('--verified-continuation', action='store_true')
    parser.add_argument('--custody-continuation', action='store_true')
    print(json.dumps(prepare(**vars(parser.parse_args())),indent=2))
