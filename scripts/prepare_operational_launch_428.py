"""Prepare a fresh immutable owner launcher around an offline r5 payload.

This reads ordinary files only. It never executes the installer, owner phase,
providers, scheduled tasks, or protected mutations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parent
for entry in (str(SCRIPTS), str(SCRIPTS.parent/'src')):
    if entry not in sys.path: sys.path.insert(0, entry)

from cochem_pipeline.routing import _strict_json
from cochem_pipeline.task_catalog_acceptance_428 import encoded
from prepare_operational_release_428 import (
    PREVIOUS_BUNDLE, PREVIOUS_ROOT, TARGET_ROOT, REVISION,
    PREVIOUS_CONFIG_SHA256, PREVIOUS_INSTALL_SHA256, _committed_script,
)
from prepare_428_release import _assert_fresh_destination, sha
from prepare_r6_launch_package import read_regular

HELPER_PIN = 'e4ac275f8bc32e41c6503e0c04472139dce10930768fbfcada3e3d1e5fcd9dcd'
LAUNCHER = 'run_operational_428_launch.ps1'


def prepare_operational_launch(payload, task_catalog_release, destination, repository, *, previous_bundle=PREVIOUS_BUNDLE,
                               codex_integration=None):
    payload, task_catalog_release, repository = map(Path, (payload, task_catalog_release, repository))
    destination = _assert_fresh_destination(Path(destination))
    release_raw = read_regular(payload/'operational-release.json')
    release = _strict_json(release_raw.decode('utf-8'))
    if (release.get('schema') != 'cochem-428-operational-release/1' or release.get('revision') != REVISION
            or release.get('target_root') != TARGET_ROOT or release.get('task_planning_enabled') is not False
            or release.get('catalog_publication_required') is not True
            or release.get('previous',{}).get('config_sha256') != PREVIOUS_CONFIG_SHA256
            or release.get('previous',{}).get('install_manifest_sha256') != PREVIOUS_INSTALL_SHA256):
        raise ValueError('Operational payload does not match the reviewed current-r4 upgrade')
    files = {'operational-release.json':release_raw}
    for row in release['files']:
        name = row['name']
        if Path(name).name != name or '/' in name or '\\' in name or name in files:
            raise ValueError('Operational payload has duplicate or unsafe inputs')
        blob = read_regular(payload/name)
        if sha(blob) != row['sha256'] or len(blob) != row['length']:
            raise ValueError('Operational payload input differs from its pin')
        files[name] = blob
    required = {'pipeline.json','install-manifest.json','source-test-evidence.json',
                'install_operational_428_runtime.ps1','stage_aetherdesk_427_payloads.ps1'}
    if not required <= files.keys(): raise ValueError('Incomplete operational payload')
    if (sha(files['pipeline.json']) != release['bootstrap_candidate_sha256']
            or sha(files['install-manifest.json']) != release['install_manifest_sha256']):
        raise ValueError('Operational bootstrap or installer differs')
    request = read_regular(task_catalog_release/'task-catalog-request.json')
    task_manifest = read_regular(task_catalog_release/'task-catalog-manifest.json')
    task = _strict_json(task_manifest.decode('utf-8'))
    if (task.get('schema') != 'cochem-task-catalog-release/4.2.8'
            or task.get('source_commit') != release['source_commit']
            or task.get('request_sha256') != sha(request) or task.get('request_bytes') != len(request)
            or task.get('configuration_sha256') != sha(encoded(_strict_json(files['pipeline.json'].decode('utf-8'))))):
        raise ValueError('Task-catalog request does not bind this exact bootstrap/source')
    helper = read_regular(Path(previous_bundle)/'run_428_launch.ps1')
    if sha(helper) != HELPER_PIN: raise ValueError('Reviewed pure helper source differs')
    files['reviewed_428_launch_helpers.ps1'] = helper
    files[LAUNCHER] = _committed_script(repository, release['source_commit'], LAUNCHER)
    files['task-catalog-request.json'] = request
    files['task-catalog-manifest.json'] = task_manifest
    integration_pin = None
    if codex_integration is not None:
        integration_raw = read_regular(Path(codex_integration))
        integration = _strict_json(integration_raw.decode('utf-8'))
        if (integration.get('schema') != 'cochem-codex-integration-update/1'
                or integration.get('source_commit') != release['source_commit']
                or integration.get('user_home') != r'C:\Users\ansac'
                or integration.get('runtime_root') != TARGET_ROOT
                or integration.get('client_config') != r'C:\Users\ansac\CoChem427\pipeline-client-r3.json'):
            raise ValueError('Codex integration is not bound to the reviewed owner/runtime/source')
        files['codex-integration.json'] = integration_raw
        integration_pin = sha(integration_raw)
    manifest = dict(schema='cochem-428-operational-launch/1',revision=REVISION,
        source_commit=release['source_commit'],previous_root=PREVIOUS_ROOT,target_root=TARGET_ROOT,
        previous_config_sha256=PREVIOUS_CONFIG_SHA256,previous_install_sha256=PREVIOUS_INSTALL_SHA256,
        install_manifest_sha256=release['install_manifest_sha256'],bootstrap_sha256=sha(files['pipeline.json']),
        request_sha256=sha(request),request_id=task['request_id'],catalog_timeout_seconds=7200,
        integration_manifest='codex-integration.json' if integration_pin else None,
        integration_sha256=integration_pin,
        input_window_minutes=20,late_prompts=False,pending_backlog_allowed=True,
        files=[dict(name=name,sha256=sha(blob),length=len(blob)) for name,blob in sorted(files.items())])
    destination.mkdir()
    for name, blob in files.items():
        with (destination/name).open('xb') as stream: stream.write(blob)
    raw = (json.dumps(manifest,indent=2)+'\n').encode()
    with (destination/'launch-manifest.json').open('xb') as stream: stream.write(raw)
    result = dict(schema='cochem-428-operational-launch-prepared/1',status='OWNER_PACKAGE_PREPARED_FOR_REVIEW',
        destination=str(destination),source_commit=release['source_commit'],launch_manifest_sha256=sha(raw),
        host_executed=False,native_acceptance_executed=False,administrator_review_required=True)
    with (destination/'launch-prepared.json').open('xb') as stream: stream.write(encoded(result))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('payload','task-catalog-release','destination','repository'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--codex-integration',type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare_operational_launch(args.payload,args.task_catalog_release,args.destination,args.repository,
        codex_integration=args.codex_integration),indent=2))


if __name__ == '__main__': main()
