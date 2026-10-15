"""Fresh offline 4.2.8 r4 -> r5 operational-repair payload; never deploys.

The old R6-derived release preparer and all delivered bundles remain immutable.
Only its generic source-freeze, offline-wheel and byte-verification helpers are
reused. The enclosing owner entry point must verify the actual running baseline,
publish native-accepted task catalog authority, then enable a final private config.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
for entry in (str(SCRIPTS), str(SCRIPTS.parent/'src')):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from cochem_pipeline.config import load_config
from cochem_pipeline.migration_428 import verify_version_alignment
from cochem_pipeline.routing import _strict_json
from prepare_428_release import (
    _assert_fresh_destination, _verify_pyproject_matches_wheelhouse,
    freeze_from_git_428, build_application_wheel_428, verify_wheel_428,
    REQUIRED_ARCHIVE_FILES, WHEEL_NAME_428, sha, validate_name_428,
)
from prepare_r6_install_bundle import read_pinned, relative
from prepare_r6_launch_package import read_regular

PREVIOUS_BUNDLE = Path(r'C:\Users\ansac\CoChem427\r428-bundle-3dab7f2')
PREVIOUS_LAUNCH_SHA256 = 'ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383'
PREVIOUS_CONFIG_SHA256 = 'daaa4b6a8c15aa49ed39af48c087bfe2fcfefdcbae14520b298d46287414509a'
PREVIOUS_INSTALL_SHA256 = 'fdf93bcbec72533eca5577b2bf5fded8da11dde38e71a13b79bd58af5ca40fa3'
PREVIOUS_COMMIT = '3dab7f2375121e0bdb82c13dc3b0add9d45179bb'
PREVIOUS_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4'
TARGET_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5'
REVISION = 'windows-20261015-428-v5'
INSTALLER = 'install_operational_428_runtime.ps1'
COPY_HELPER = 'stage_aetherdesk_427_payloads.ps1'
COPY_HELPER_SHA256 = '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'


def read_current_baseline(directory=PREVIOUS_BUNDLE):
    """Verify the ordinary saved baseline, not the currently running host state."""
    directory = Path(directory)
    launch_raw = read_regular(directory/'launch-manifest.json')
    if sha(launch_raw) != PREVIOUS_LAUNCH_SHA256:
        raise ValueError('Saved current-r4 launch manifest differs from its reviewed pin')
    launch = _strict_json(launch_raw.decode('utf-8'))
    expected = dict(source_commit=PREVIOUS_COMMIT, candidate_sha256=PREVIOUS_CONFIG_SHA256,
                    install_manifest_sha256=PREVIOUS_INSTALL_SHA256, revision='windows-20261014-428-v4')
    if any(launch.get(key) != value for key, value in expected.items()):
        raise ValueError('Saved current-r4 launch identity differs')
    config_raw = read_regular(directory/'pipeline.json')
    install_raw = read_regular(directory/'install-manifest.json')
    if sha(config_raw) != PREVIOUS_CONFIG_SHA256 or sha(install_raw) != PREVIOUS_INSTALL_SHA256:
        raise ValueError('Saved current-r4 configuration or install manifest changed')
    install = _strict_json(install_raw.decode('utf-8'))
    rows = [row for row in install['files'] if row['relative'] == 'pipeline.json']
    if (install.get('source_commit') != PREVIOUS_COMMIT or len(rows) != 1
            or rows[0]['sha256'] != PREVIOUS_CONFIG_SHA256 or rows[0]['length'] != len(config_raw)):
        raise ValueError('Saved current-r4 install/configuration binding differs')
    return config_raw, dict(runtime_root=PREVIOUS_ROOT, source_commit=PREVIOUS_COMMIT,
        config_sha256=PREVIOUS_CONFIG_SHA256, install_manifest_sha256=PREVIOUS_INSTALL_SHA256,
        launch_manifest_sha256=PREVIOUS_LAUNCH_SHA256, actual_host_verified=False)


def bootstrap_from_current_428(previous_bytes, *, expected_previous_pin=PREVIOUS_CONFIG_SHA256,
                               coding_registration=None):
    """Only explicit bootstrap changes; no provider/model/quota authority invented."""
    if sha(previous_bytes) != expected_previous_pin:
        raise ValueError('Current-r4 configuration differs from reviewed pin')
    previous = _strict_json(previous_bytes.decode('utf-8'))
    if previous.get('runtime_version') != '4.2.8' or previous.get('max_execution_slots') != 4:
        raise ValueError('Upgrade requires current 4.2.8 and four shared execution slots')
    candidate = deepcopy(previous)
    for key in ('source_root', 'wiki_root', 'manifest_path'):
        path = candidate.get('knowledge', {}).get(key)
        if not isinstance(path, str) or not path.startswith(PREVIOUS_ROOT + '\\source\\knowledge\\'):
            raise ValueError('Current-r4 knowledge source binding differs')
        candidate['knowledge'][key] = TARGET_ROOT + path[len(PREVIOUS_ROOT):]
    candidate['catalog_activation'] = True
    candidate['task_planning'] = None
    if coding_registration is not None:
        from cochem_pipeline.project_registration import RegistrationPolicy
        RegistrationPolicy.from_dict(coding_registration)
        candidate['coding_registration'] = deepcopy(coding_registration)
    # Everything else, including actual native selector contracts, old project
    # definitions, pools, credentials, repair budgets and knowledge DBs stays put.
    return candidate


def _committed_script(repository, commit, name):
    raw = read_regular(Path(repository)/'scripts'/name)
    committed = subprocess.run(['git', '-C', str(repository), 'show', commit+':scripts/'+name],
                               capture_output=True, check=True, timeout=15).stdout
    # Git may normalize working checkout line endings; package committed bytes.
    if raw.replace(b'\r\n', b'\n') != committed.replace(b'\r\n', b'\n'):
        raise ValueError('Release script differs from the frozen source commit: '+name)
    return committed


def prepare_operational_release_428(freeze, wheelhouse, application, destination, repository, *,
                                    previous_bundle=PREVIOUS_BUNDLE, coding_registration=None):
    freeze, wheelhouse, application, repository = map(Path, (freeze, wheelhouse, application, repository))
    destination = _assert_fresh_destination(Path(destination))
    source_raw = read_regular(freeze/'source-preparation.json')
    source = _strict_json(source_raw.decode('utf-8'))
    wheels = _strict_json(read_regular(wheelhouse/'wheelhouse-verified.json').decode('utf-8'))
    app = _strict_json(read_regular(application).decode('utf-8'))
    if (source.get('schema') != 'cochem-428-source-preparation/1' or source.get('version') != '4.2.8'
            or not re.fullmatch('[a-f0-9]{40}', str(source.get('commit', '')))
            or wheels.get('status') != 'LOCKED_RUNTIME_WHEELS_VERIFIED'
            or app.get('status') != 'APPLICATION_WHEEL_VERIFIED' or app.get('version') != '4.2.8'
            or app.get('source_commit') != source['commit'] or app.get('source_manifest_sha256') != sha(source_raw)
            or wheels.get('lock_sha256') != sha(read_regular(freeze/'uv.lock'))):
        raise ValueError('Offline payloads do not bind the same source and dependencies')
    _verify_pyproject_matches_wheelhouse(read_regular(freeze/'pyproject.toml'), wheels['pyproject_sha256'])
    verified = verify_wheel_428(Path(app['wheel']), freeze)
    if any(verified[key] != app[key] for key in ('sha256', 'size', 'files')):
        raise ValueError('Application wheel differs from its verified record')
    previous_raw, baseline = read_current_baseline(previous_bundle)
    candidate = bootstrap_from_current_428(previous_raw, coding_registration=coding_registration)
    scripts = {name: _committed_script(repository, source['commit'], name) for name in (INSTALLER, COPY_HELPER)}
    # Preserve the copy helper's literal reviewed bytes; its importer pins bytes,
    # not normalized text. A Git checkout/source conversion cannot change them.
    if sha(scripts[COPY_HELPER]) != COPY_HELPER_SHA256:
        actual = read_regular(repository/'scripts'/COPY_HELPER)
        if sha(actual) != COPY_HELPER_SHA256:
            raise ValueError('Reviewed offline copy helper pin differs')
        scripts[COPY_HELPER] = actual
    files, seen, requirements = [], set(), []
    def add(name, path, pin, size):
        relative(name)
        if name.casefold() in seen:
            raise ValueError('Duplicate offline payload path')
        seen.add(name.casefold())
        read_pinned(Path(path), pin, size)
        files.append(dict(relative=name, source=str(Path(path).absolute()), sha256=pin, length=size))
    source_names = set()
    for row in source['files']:
        validate_name_428(row['relative'])
        source_names.add(row['relative'])
        add('source/'+row['relative'], freeze/row['relative'], row['sha256'], row['length'])
    if not REQUIRED_ARCHIVE_FILES <= source_names:
        raise ValueError('Offline source omits required 4.2.8 assets')
    for row in wheels['files']:
        filename = row['filename']
        relative(filename)
        if ('/' in filename or not re.fullmatch('[a-z0-9][a-z0-9.-]*', row['name'])
                or not re.fullmatch('[A-Za-z0-9.+!-]+', row['version'])):
            raise ValueError('Invalid locked dependency identity')
        add('wheels/'+filename, wheelhouse/filename, row['sha256'], row['size'])
        requirements.append(f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}")
    add('wheels/'+WHEEL_NAME_428, Path(app['wheel']), app['sha256'], app['size'])
    requirements.append('cochem==4.2.8 --hash=sha256:'+app['sha256'])
    destination.mkdir()
    def write(name, value):
        raw = value if isinstance(value, bytes) else (json.dumps(value, indent=2, ensure_ascii=False)+'\n').encode('utf-8')
        with (destination/name).open('xb') as stream:
            stream.write(raw)
        return raw
    try:
        config_raw = write('pipeline.json', candidate)
        parsed = load_config(destination/'pipeline.json')
        alignment = verify_version_alignment(parsed)
        if (parsed.max_execution_slots != 4 or parsed.task_planning is not None or not parsed.catalog_activation
                or alignment['status'] != 'VERSION_ALIGNMENT_VERIFIED'):
            raise ValueError('Operational bootstrap configuration failed validation')
        add('pipeline.json', destination/'pipeline.json', sha(config_raw), len(config_raw))
        req = write('runtime-requirements.txt', ('\n'.join(requirements)+'\n').encode('utf-8'))
        add('wheels/runtime-requirements.txt', destination/'runtime-requirements.txt', sha(req), len(req))
        evidence = dict(schema='cochem-428-source-test-evidence/1', version='4.2.8',
            source_commit=source['commit'], source_manifest_sha256=sha(source_raw),
            validation_doc_sha256=sha(read_regular(freeze/'docs/4.2.8/VALIDATION.md')),
            runner='scripts/run_source_tests_428.py', tests_executed_by_preparer=False,
            host_acceptance_executed=False)
        evidence_pin = sha(write('source-test-evidence.json', evidence))
        manifest = dict(schema='cochem-428-install-bundle/1', host='AETHERDESK', revision=REVISION,
            version='4.2.8', source_commit=source['commit'], source_test_evidence_sha256=evidence_pin,
            files=files, activation_ready=False)
        install_pin = sha(write('install-manifest.json', manifest))
        for name, raw in scripts.items():
            write(name, raw)
        metadata = dict(schema='cochem-428-operational-release/1', version='4.2.8', revision=REVISION,
            previous=baseline, target_root=TARGET_ROOT, source_commit=source['commit'],
            install_manifest_sha256=install_pin, bootstrap_candidate_sha256=sha(config_raw),
            source_test_evidence_sha256=evidence_pin, task_planning_enabled=False,
            catalog_publication_required=True, coding_registration=candidate.get('coding_registration'),
            files=[dict(name=name, sha256=sha(read_regular(destination/name)), length=(destination/name).stat().st_size)
                   for name in (INSTALLER, COPY_HELPER, 'pipeline.json', 'install-manifest.json',
                                'source-test-evidence.json', 'runtime-requirements.txt')],
            stale_recovery_included=False, input_window_minutes=20, late_prompts=False,
            owner_entrypoint_included=False, actual_host_verified=False, activation_ready=False)
        release_pin = sha(write('operational-release.json', metadata))
        result = dict(schema='cochem-428-operational-package-preparation/1',
            status='OFFLINE_OPERATIONAL_PAYLOAD_PREPARED', destination=str(destination),
            target_root=TARGET_ROOT, revision=REVISION, source_commit=source['commit'], payload_files=len(files),
            install_manifest_sha256=install_pin, release_manifest_sha256=release_pin,
            bootstrap_candidate_sha256=sha(config_raw), administrator_launch_ready=False,
            host_acceptance_executed=False, activation_ready=False)
        write('package-prepared.json', result)
        return result
    except Exception as exc:
        write('package-held.json', dict(status='HELD_PRESERVE_PARTIAL', error_type=type(exc).__name__,
                                       automatic_retry=False, activation_ready=False))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('freeze', 'wheelhouse', 'application', 'destination', 'repository'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--previous-bundle', type=Path, default=PREVIOUS_BUNDLE)
    parser.add_argument('--coding-registration', type=Path)
    args = parser.parse_args()
    registration = (_strict_json(read_regular(args.coding_registration).decode('utf-8'))
                    if args.coding_registration else None)
    print(json.dumps(prepare_operational_release_428(args.freeze, args.wheelhouse, args.application,
        args.destination, args.repository, previous_bundle=args.previous_bundle,
        coding_registration=registration), indent=2))


if __name__ == '__main__':
    main()
