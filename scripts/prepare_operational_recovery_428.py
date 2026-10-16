"""Prepare a fresh offline launcher for the one reviewed expired-fence recovery.

The installed runtime and original launch inputs remain immutable. This only
reads ordinary source inputs, verifies their pins, and writes a new user-owned
package. It never interprets an ordinary diagnostic as execution authority;
the owner entrypoint must reopen the pinned protected receipts and task state.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import uuid

SCRIPTS = Path(__file__).resolve().parent
for entry in (str(SCRIPTS), str(SCRIPTS.parent / 'src')):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from cochem_pipeline.routing import _strict_json
from prepare_428_release import _assert_fresh_destination, sha
from prepare_operational_release_428 import (
    PREVIOUS_ROOT, TARGET_ROOT, REVISION, PREVIOUS_CONFIG_SHA256,
    PREVIOUS_INSTALL_SHA256, _committed_script,
)
from prepare_r6_install_bundle import relative
from prepare_r6_launch_package import read_regular

ORIGINAL_LAUNCH = Path(r'C:\Users\ansac\CoChem427\r428-op-launch-865a29b')
ORIGINAL_LAUNCH_SHA256 = '49481181faa25f4b8762b85013bece21afb3f58b3f9b8e7417237fa3dacfc75c'
RUNTIME_SOURCE_COMMIT = '865a29b113a8b59c822f6aa4d921a45c18407fe5'
LAUNCHER = 'run_operational_428_launch.ps1'
RECOVERY_NAME = 'admission-recovery.json'
EVIDENCE_NAME = 'recovery-source-test-evidence.json'
ORIGINAL_NAME = 'original-launch-manifest.json'
_ORIGINAL_FIELDS = {'schema', 'revision', 'source_commit', 'previous_root', 'target_root',
    'previous_config_sha256', 'previous_install_sha256', 'install_manifest_sha256', 'bootstrap_sha256',
    'request_sha256', 'request_id', 'catalog_timeout_seconds', 'integration_manifest', 'integration_sha256',
    'input_window_minutes', 'late_prompts', 'pending_backlog_allowed', 'files'}
_REQUIRED_FILES = {LAUNCHER, 'pipeline.json', 'install-manifest.json', 'source-test-evidence.json',
    'task-catalog-request.json', 'task-catalog-manifest.json', 'operational-release.json',
    'codex-integration.json', 'reviewed_428_launch_helpers.ps1', 'install_operational_428_runtime.ps1',
    'stage_aetherdesk_427_payloads.ps1', 'runtime-requirements.txt'}
_RESERVED_NAMES = {RECOVERY_NAME, EVIDENCE_NAME, ORIGINAL_NAME, 'launch-manifest.json', 'launch-prepared.json'}


def _hex(value, length):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{' + str(length) + '}', value):
        raise ValueError('A full lowercase source commit, recovery identity or SHA256 pin is required')
    return value


STOPPED_SCENARIO = 'INSTALLED_R5_EXPIRED_FENCE_20261015'
RUNNING_SCENARIO = 'INSTALLED_R5_RUNNING_R4_20261016'


def make_recovery_spec(launcher_source_commit, *, recovery_id=None, scenario='stopped'):
    """Literal reviewed evidence shared with Get-OpRecoveryExpected (stopped) and
    Get-OpRunningRecoveryExpected (running) in the launcher."""
    if scenario not in ('stopped', 'running'):
        raise ValueError('Recovery scenario must be stopped or running')
    spec = dict(schema='cochem-428-admission-recovery/1', scenario='INSTALLED_R5_EXPIRED_FENCE_20261015',
        recovery_id=_hex(recovery_id if recovery_id is not None else uuid.uuid4().hex, 32),
        launcher_source_commit=_hex(launcher_source_commit, 40), runtime_source_commit=RUNTIME_SOURCE_COMMIT,
        original_launch_manifest_sha256=ORIGINAL_LAUNCH_SHA256,
        original_sitting=r'C:\Program Files\CoChem\R428Operational-20261015-a62bffb278044fffbaf21207a866ff81',
        install_after_sha256='0d4b036eda13a5381b700d766aa7eb097cbc893f6e0a6ff07b770e53bbe947ae',
        baseline_sha256='6dfc1cab0ebce9b73d341d03cf99d1e769b4351446d0af7b7ccc5ccd4e150767',
        owner_result_sha256='de2dde03d0cb6abfe681eafe6cc0814cdacfa0c1dce29ce0bd51cb1ac5a83652',
        fence=dict(directory='stop-fence-d8196aa484dc4562a213e19faf9e3b05',
            nonce='a232264b12984ff2ab9ef33b7ec24c75', pid=46440,
            started_sha256='ac89c6175162298f10ebf05623bcfaaa884bc740e9673603ce657e73a0c07317',
            ready_sha256='c13d512da76fefa0ea1b6509eb35282f80d3c0a4135396f7ac5c6814b86f7912',
            result_sha256='2e808d80b655db392ce0d0dda8b93d828c604e7b296088cc63d1603b1ac8ce28',
            task_xml_sha256='351e830d81725f0d103ff69347cd4b889b4911548165d829dd725910a2df5004',
            task_sddl_sha256='bcacae79e462afbe0623b80a0898c24360cf59472d049fd6bc264d6308c04eff',
            last_run_utc='2026-10-15T18:41:18Z', last_task_result=2),
        warden=dict(pid=24424, task_xml_sha256='aa3efe0fce92975a3b407dba19b6195368bfbd7f56fa438c77d3f4e509e93fe5',
            task_sddl_sha256='bcacae79e462afbe0623b80a0898c24360cf59472d049fd6bc264d6308c04eff',
            last_run_utc='2026-10-15T01:37:07Z', last_task_result=1))
    if scenario == 'running':
        # The reboot-started r4 is bound live; only reboot-stable facts stay pinned.
        old = spec['warden']
        spec.update(schema='cochem-428-admission-recovery/2', scenario=RUNNING_SCENARIO,
            warden=dict(pid=old['pid'], task_xml_sha256=old['task_xml_sha256'],
                task_sddl_sha256=old['task_sddl_sha256'], last_run_after_utc=old['last_run_utc']))
    return spec


def validate_recovery_spec(value):
    if not isinstance(value, dict):
        raise ValueError('Recovery must use the exact reviewed contract')
    scenario = 'running' if value.get('scenario') == RUNNING_SCENARIO else 'stopped'
    expected = make_recovery_spec(value.get('launcher_source_commit'), recovery_id=value.get('recovery_id'), scenario=scenario)
    # JSON comparison also distinguishes booleans from integer receipt fields.
    if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True):
        raise ValueError('Recovery differs from the exact reviewed evidence contract')
    return value


def _pinned(path, pin, length, *, maximum=256 * 1024**2):
    _hex(pin, 64)
    if type(length) is not int or not 0 <= length <= maximum:
        raise ValueError('Pinned input length is outside its bound')
    raw = read_regular(path, maximum=maximum)
    if len(raw) != length or sha(raw) != pin:
        raise ValueError('Original pinned input digest or length differs')
    return raw


def _verify_install_inputs(files, manifest):
    install = _strict_json(files['install-manifest.json'].decode('utf-8'))
    if (not isinstance(install, dict) or install.get('schema') != 'cochem-428-install-bundle/1'
            or install.get('version') != '4.2.8' or install.get('revision') != REVISION
            or install.get('source_commit') != RUNTIME_SOURCE_COMMIT
            or install.get('source_test_evidence_sha256') != sha(files['source-test-evidence.json'])
            or sha(files['install-manifest.json']) != manifest['install_manifest_sha256']):
        raise ValueError('Original install inventory differs from the reviewed runtime')
    rows = install.get('files')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError('Original install inventory must be bounded')
    seen, total = set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'relative', 'source', 'sha256', 'length'}:
            raise ValueError('Original install inventory has unexpected fields')
        name = relative(row['relative'])
        if name.casefold() in seen:
            raise ValueError('Original install inventory has a duplicate destination')
        seen.add(name.casefold())
        source = row['source']
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise ValueError('Original install source must be an absolute ordinary file')
        if type(row['length']) is not int or row['length'] < 0:
            raise ValueError('Original install input length is invalid')
        total += row['length']
        if total > 1024 * 1024**2:
            raise ValueError('Original install inputs exceed the total bound')
        # Read one input at a time; do not retain the wheelhouse in memory.
        _pinned(Path(source), row['sha256'], row['length'])
    return len(rows), total


def _read_original(directory):
    raw = read_regular(directory / 'launch-manifest.json')
    if sha(raw) != ORIGINAL_LAUNCH_SHA256:
        raise ValueError('Original launch manifest differs from its reviewed pin')
    manifest = _strict_json(raw.decode('utf-8'))
    expected = dict(schema='cochem-428-operational-launch/1', revision=REVISION,
        source_commit=RUNTIME_SOURCE_COMMIT, previous_root=PREVIOUS_ROOT, target_root=TARGET_ROOT,
        previous_config_sha256=PREVIOUS_CONFIG_SHA256, previous_install_sha256=PREVIOUS_INSTALL_SHA256,
        catalog_timeout_seconds=7200, input_window_minutes=20, late_prompts=False, pending_backlog_allowed=True,
        integration_manifest='codex-integration.json')
    if (not isinstance(manifest, dict) or set(manifest) != _ORIGINAL_FIELDS
            or any(type(manifest.get(key)) is not type(value) or manifest[key] != value for key, value in expected.items())):
        raise ValueError('Original launch source, runtime identity or unattended contract differs')
    rows = manifest['files']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1024:
        raise ValueError('Original launch input inventory must be bounded')
    files, names, total = {}, set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'name', 'sha256', 'length'}:
            raise ValueError('Original launch input row has unexpected fields')
        name = relative(row['name'])
        if '/' in name or name.casefold() in names or name.casefold() in _RESERVED_NAMES:
            raise ValueError('Original launch input name is unsafe, reserved or duplicated')
        names.add(name.casefold())
        blob = _pinned(directory / name, row['sha256'], row['length'], maximum=16 * 1024**2)
        total += len(blob)
        if total > 128 * 1024**2:
            raise ValueError('Original launch inputs exceed the total bound')
        files[name] = blob
    if not _REQUIRED_FILES <= files.keys():
        raise ValueError('Original launch package is missing a required input')
    for name, field in [('pipeline.json', 'bootstrap_sha256'), ('install-manifest.json', 'install_manifest_sha256'),
                        ('task-catalog-request.json', 'request_sha256'), ('codex-integration.json', 'integration_sha256')]:
        if sha(files[name]) != manifest[field]:
            raise ValueError('Original runtime, request or integration pin differs')
    _hex(manifest['request_id'], 32)
    count, size = _verify_install_inputs(files, manifest)
    return raw, manifest, files, count, size


def _read_test_evidence(path, pin, launcher_source_commit):
    _hex(pin, 64)
    raw = read_regular(path, maximum=1024 * 1024)
    if sha(raw) != pin:
        raise ValueError('Recovery source-test evidence differs from its pin')
    value = _strict_json(raw.decode('utf-8'))
    expected = dict(schema='cochem-428-operational-recovery-source-tests/1',
        launcher_source_commit=launcher_source_commit, runtime_source_commit=RUNTIME_SOURCE_COMMIT,
        runner='scripts/run_source_tests_428.py', status='PASSED', failed=0, host_acceptance_executed=False)
    if (not isinstance(value, dict) or set(value) != set(expected) | {'passed', 'source_test_report_sha256'}
            or any(type(value.get(key)) is not type(want) or value[key] != want for key, want in expected.items())
            or type(value['passed']) is not int or not 1 <= value['passed'] <= 100000):
        raise ValueError('Recovery source-test evidence is not bound to the chosen launcher source')
    _hex(value['source_test_report_sha256'], 64)
    return raw


def _encode(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _write(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def prepare_operational_recovery(original_launch, destination, repository, *, launcher_source_commit,
                                 recovery_source_tests, recovery_source_tests_sha256, recovery_id=None,
                                 scenario='stopped'):
    original_launch, destination, repository = map(Path, (original_launch, destination, repository))
    if not all(path.is_absolute() for path in (original_launch, destination, repository, Path(recovery_source_tests))):
        raise ValueError('Recovery preparation requires explicit absolute ordinary paths')
    destination = _assert_fresh_destination(destination)
    _hex(launcher_source_commit, 40)
    recovery = make_recovery_spec(launcher_source_commit, recovery_id=recovery_id, scenario=scenario)
    validate_recovery_spec(recovery)
    original_raw, original, files, install_count, install_size = _read_original(original_launch)
    launcher = _committed_script(repository, launcher_source_commit, LAUNCHER)
    if b'function Assert-OpRecoveryManifest' not in launcher:
        raise ValueError('Chosen committed launcher lacks the reviewed recovery entrypoint')
    if scenario == 'running' and b'function Assert-OpRunningRecoveryEvidence' not in launcher:
        raise ValueError('Chosen committed launcher lacks the running-r4 recovery entrypoint')
    evidence = _read_test_evidence(Path(recovery_source_tests), recovery_source_tests_sha256, launcher_source_commit)
    files[LAUNCHER] = launcher
    files[ORIGINAL_NAME] = original_raw
    files[RECOVERY_NAME] = _encode(recovery)
    files[EVIDENCE_NAME] = evidence
    manifest = deepcopy(original)
    manifest.update(launcher_source_commit=launcher_source_commit, recovery_manifest=RECOVERY_NAME,
                    recovery_sha256=sha(files[RECOVERY_NAME]),
                    files=[dict(name=name, sha256=sha(blob), length=len(blob)) for name, blob in sorted(files.items())])
    manifest_raw = _encode(manifest)
    result = dict(schema='cochem-428-operational-recovery-prepared/1', status='OWNER_RECOVERY_PACKAGE_PREPARED_FOR_REVIEW',
        destination=str(destination), source_commit=RUNTIME_SOURCE_COMMIT, launcher_source_commit=launcher_source_commit,
        recovery_id=recovery['recovery_id'], scenario=recovery['scenario'], original_launch_manifest_sha256=ORIGINAL_LAUNCH_SHA256,
        launch_manifest_sha256=sha(manifest_raw), recovery_sha256=manifest['recovery_sha256'],
        recovery_source_tests_sha256=sha(evidence), launch_inputs_verified=len(files),
        original_install_inputs_verified=install_count, original_install_input_bytes=install_size,
        host_executed=False, native_acceptance_executed=False, source_tests_executed_by_preparer=False,
        administrator_review_required=True)
    # Every validation, including external original install inputs, finishes
    # before the first output write. Never remove partial output after an I/O error.
    destination = _assert_fresh_destination(destination)
    destination.mkdir()
    for name, blob in sorted(files.items()):
        _write(destination / name, blob)
    _write(destination / 'launch-manifest.json', manifest_raw)
    for row in manifest['files']:
        _pinned(destination / row['name'], row['sha256'], row['length'])
    _write(destination / 'launch-prepared.json', _encode(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-launch', type=Path, default=ORIGINAL_LAUNCH)
    for name in ('destination', 'repository', 'recovery-source-tests'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--launcher-source-commit', required=True)
    parser.add_argument('--recovery-source-tests-sha256', required=True)
    parser.add_argument('--recovery-id')
    # Explicit: a package for the wrong host state is spent on its first hold.
    parser.add_argument('--scenario', choices=('stopped', 'running'), required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_operational_recovery(**vars(args)), indent=2))


if __name__ == '__main__':
    main()
