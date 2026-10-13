"""Prepare fresh R7 offline inputs; never installs or executes host acceptance."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import uuid
import re

from cochem_pipeline.config import load_config
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.catalog_activation import compile_change
from cochem_pipeline.routing_catalog import retire_owner_gemini_pro
from prepare_r6_install_bundle import read_pinned, relative
from prepare_r6_launch_package import read_regular
from build_r6_application import verify_wheel

def sha(data):return hashlib.sha256(data).hexdigest()

PREVIOUS=Path(r'C:\Users\ansac\CoChem427\r6-bundle-359ca92\pipeline.json')
PREVIOUS_PIN='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
RECOVERY=Path(r'C:\Users\ansac\CoChem427\r6-auth-recovery-eb982cb')
RECOVERY_PIN='bc1cb7b2c1ac4eac872cfde38b57f382cdef24388a9902f9899020bd10dfbf58'

def derive_recovery_entry(raw):
    old=b'param([string]$LaunchManifest,[string]$LaunchManifestSha256,[switch]$Apply)'
    deadline=b'$script:R6InputDeadline=[DateTime]::UtcNow.AddMinutes(20)'
    if raw.count(old)!=1 or raw.count(deadline)!=1:raise ValueError('Reviewed recovery entry sites changed')
    return raw.replace(old,old[:-1]+b',[string]$OwnerInputDeadlineUtc)') .replace(deadline,deadline+b'''
        if($OwnerInputDeadlineUtc){
            $outer=[DateTime]::Parse($OwnerInputDeadlineUtc,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
            if($outer -lt $script:R6InputDeadline){$script:R6InputDeadline=$outer}
            if([DateTime]::UtcNow -ge $script:R6InputDeadline){throw 'The owner-input window is already closed.'}
        }''')

def prepare_recovery(destination, repository):
    raw=RECOVERY.joinpath('launch-manifest.json').read_bytes()
    if sha(raw)!=RECOVERY_PIN:raise ValueError('Reviewed R6 prerequisite recovery changed')
    manifest=json.loads(raw);destination.mkdir()
    for row in manifest['scripts']:
        relative(row['name'])
        if '/' in row['name']:raise ValueError('Unexpected recovery input path')
        payload=read_pinned(RECOVERY/row['name'],row['sha256'],row['length'])
        if row['name']=='run_r6_launch.ps1':
            payload=derive_recovery_entry(read_regular(Path(repository)/'scripts'/row['name']))
        elif row['name'] in ('r6_auth_recovery.py','verify_r6_auth_recovery.ps1','run_r6_system_phase.ps1','activate_r6_runtime.ps1','r6_attended_agy.ps1'):
            # Replace only reviewed recovery helpers in this fresh copy. Earlier
            # delivered packages and all remaining R5/R6 inputs stay untouched.
            payload=read_regular(Path(repository)/'scripts'/row['name'])
        with (destination/row['name']).open('xb') as out:out.write(payload)
        row.update(sha256=sha(payload),length=len(payload))
    for name,relative_source in (
        ('r6_native_retirement.py','scripts/r6_native_retirement.py'),
        ('login_pipeline_worker_agy_terminal.ps1','scripts/login_pipeline_worker_agy_terminal.ps1'),
        ('worker_agy_terminal_bridge.py','scripts/worker_agy_terminal_bridge.py'),
        ('attended_agy_terminal.py','src/cochem_pipeline/attended_agy_terminal.py')):
        payload=read_regular(Path(repository)/relative_source)
        with destination.joinpath(name).open('xb') as out:out.write(payload)
        manifest['scripts'].append(dict(name=name,sha256=sha(payload),length=len(payload)))
    raw=(json.dumps(manifest,indent=2)+'\n').encode()
    with destination.joinpath('launch-manifest.json').open('xb') as out:out.write(raw)
    return dict(directory=str(destination),manifest_sha256=sha(raw),original_manifest_sha256=RECOVERY_PIN,
        entry_sha256=sha(destination.joinpath('run_r6_launch.ps1').read_bytes()),input_deadline_inherited=True,
        reviewed_prefix_recovery=True,owner_model_retirement='owner-2026-10-12-pro-retired')

def candidate_from_previous(data):
    if sha(data)!=PREVIOUS_PIN:raise ValueError('Previously installed R6 configuration differs')
    candidate=json.loads(data);candidate['catalog_activation']=True
    policy=load_routing_policy(candidate['routing'])
    catalog=retire_owner_gemini_pro(policy.as_dict()['catalog'])
    change=compile_change(policy,catalog,expected_policy_digest=policy.digest)
    return candidate,change

def derive_installer(raw):
    if raw.count(b'windows-20261012-r6-v1')!=2:raise ValueError('Reviewed installer revision sites changed')
    return raw.replace(b'windows-20261012-r6-v1',b'windows-20261012-r7-v1')

def prepare(freeze,wheelhouse,application,destination,repository):
    freeze,wheelhouse,application,destination,repository=map(Path,(freeze,wheelhouse,application,destination,repository))
    if destination.exists() or not destination.is_absolute() or not destination.parent.is_dir() or any(
            'gdrive' in p.lower() or 'google drive' in p.lower() for p in destination.parts):
        raise ValueError('A fresh ordinary bundle outside Google Drive is required')
    for path in (destination.parent,*destination.parent.parents):
        if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('Bundle destination traverses a redirected path')
    source=json.loads((freeze/'source-preparation.json').read_text())
    wheels=json.loads((wheelhouse/'wheelhouse-verified.json').read_text())
    app=json.loads(application.read_text())
    if (source['schema']!='cochem-r6-source-preparation/1' or not re.fullmatch('[a-f0-9]{40}',source['commit'])
            or wheels['status']!='LOCKED_RUNTIME_WHEELS_VERIFIED' or app['status']!='APPLICATION_WHEEL_VERIFIED'
            or app['source_commit']!=source['commit'] or wheels['lock_sha256']!=sha((freeze/'uv.lock').read_bytes())
            or wheels['pyproject_sha256']!=sha((freeze/'pyproject.toml').read_bytes())
            or app['source_manifest_sha256']!=sha((freeze/'source-preparation.json').read_bytes())):
        raise ValueError('Offline payloads bind different source or dependency sets')
    verified=verify_wheel(Path(app['wheel']),freeze)
    if any(verified[k]!=app[k] for k in ('sha256','size','files')):raise ValueError('Application wheel changed')
    candidate,change=candidate_from_previous(PREVIOUS.read_bytes())
    proposal=dict(schema='cochem-catalog-change-request/1',previous_policy_digest=change.previous_policy_digest,
        catalog=change.policy.as_dict()['catalog'])
    files=[];requirements=[];seen=set()
    def write(name,value):
        raw=value if isinstance(value,bytes) else (json.dumps(value,indent=2)+'\n').encode()
        with (destination/name).open('xb') as out:out.write(raw)
        return raw
    def add(name,path,pin,size):
        relative(name)
        if name.casefold() in seen:raise ValueError('Duplicate bundle payload')
        seen.add(name.casefold());read_pinned(path,pin,size)
        files.append(dict(relative=name,source=str(path.absolute()),sha256=pin,length=size))
    for row in source['files']:add('source/'+row['relative'],freeze/row['relative'],row['sha256'],row['length'])
    for row in wheels['files']:
        relative(row['filename'])
        if '/' in row['filename'] or not re.fullmatch('[a-z0-9][a-z0-9.-]*',row['name']) or not re.fullmatch('[A-Za-z0-9.+!-]+',row['version']):
            raise ValueError('Invalid locked wheel identity')
        add('wheels/'+row['filename'],wheelhouse/row['filename'],row['sha256'],row['size'])
        requirements.append(f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}")
    add('wheels/cochem-4.2.7-py3-none-any.whl',Path(app['wheel']),app['sha256'],app['size'])
    requirements.append('cochem==4.2.7 --hash=sha256:'+app['sha256'])
    installer=derive_installer((repository/'scripts/install_r6_runtime.ps1').read_bytes())
    destination.mkdir()
    recovery=prepare_recovery(destination/'r6-prerequisite',repository)
    raw=write('pipeline.json',candidate);load_config(destination/'pipeline.json')
    add('pipeline.json',destination/'pipeline.json',sha(raw),len(raw))
    raw=write('runtime-requirements.txt',('\n'.join(requirements)+'\n').encode())
    add('wheels/runtime-requirements.txt',destination/'runtime-requirements.txt',sha(raw),len(raw))
    manifest=dict(schema='cochem-r6-install-bundle/1',host='AETHERDESK',revision='windows-20261012-r7-v1',
        source_commit=source['commit'],files=files,activation_ready=False)
    manifest_hash=sha(write('install-manifest.json',manifest))
    proposal_bytes=write('proposal.json',proposal);proposal_hash=sha(proposal_bytes)
    pointer=dict(schema='cochem-catalog-authority-pointer/1',request_id=uuid.uuid4().hex,proposal_sha256=proposal_hash)
    write('pointer.json',pointer)
    # Derive the reviewed stopped installer while preserving the delivered R6 files.
    write('install_r7_runtime.ps1',installer)
    write('stage_aetherdesk_427_payloads.ps1',(repository/'scripts/stage_aetherdesk_427_payloads.ps1').read_bytes())
    write('run_r7_launch.ps1',(repository/'scripts/run_r7_launch.ps1').read_bytes())
    package_files=[]
    for name in ('install_r7_runtime.ps1','stage_aetherdesk_427_payloads.ps1','run_r7_launch.ps1',
                 'pipeline.json','install-manifest.json','proposal.json','pointer.json'):
        raw=(destination/name).read_bytes();package_files.append(dict(name=name,sha256=sha(raw),length=len(raw)))
    launch=dict(schema='cochem-r7-launch-package/1',host='AETHERDESK',files=package_files,
        install_manifest_sha256=manifest_hash,candidate_sha256=sha((destination/'pipeline.json').read_bytes()),
        expected_r6_candidate_sha256=PREVIOUS_PIN,proposal_sha256=proposal_hash,request_id=pointer['request_id'],
        baseline_policy_digest=change.previous_policy_digest,catalog_policy_digest=change.policy.digest,
        r6_prerequisite=recovery,
        source_commit=source['commit'],input_window_minutes=20,late_prompts=False)
    pin=sha(write('launch-manifest.json',launch))
    result=dict(status='R7_OFFLINE_PACKAGE_PREPARED',launch_manifest_sha256=pin,
        payload_files=len(files),source_commit=source['commit'],catalog_plan_digest=change.digest,
        host_acceptance_executed=False)
    write('package-prepared.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('freeze','wheelhouse','application','destination','repository'):p.add_argument('--'+name,required=True)
    print(json.dumps(prepare(**vars(p.parse_args())),indent=2))
