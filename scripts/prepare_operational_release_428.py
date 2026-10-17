"""Fresh offline 4.2.8 operational payload (r4 -> r5, spent; r4 -> r6); never deploys.

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
# r5 stays installed and spent; r6 is a fresh root installed beside it.
R6_TARGET_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.8-windows-20261017-r6'
R6_REVISION = 'windows-20261017-428-v6'
RELEASES = {'r5': (TARGET_ROOT, REVISION), 'r6': (R6_TARGET_ROOT, R6_REVISION)}
# The board's active routing policy: r4's own launch published it on
# 2026-10-14 from the saved bundle above (request b8ef2785...). The catalog
# phase must target it, and its candidate must route it (enabled_candidate).
BASELINE_POLICY_DIGEST = '6a76497a281e5ec23fca7f4a8d14a5581c5a35e71a94a0757ac95e7687e0e3c4'
ACTIVE_POLICY_DIGEST = 'c8444fe2fd46b0f53edeaefc677ef7ff698c3e11cb83348a70255026a81da43d'
RETIRED_GEMINI_BINDINGS = frozenset({'gemini-3.1-pro:high'})
CODEX_CAPABILITY_REFERENCE = ('Codex -c model_reasoning_effort selector on the exact codex-cli 0.160.0 '
    'binary (offline config load, docs/evidence/windows-2026-10-06); per-target native acceptance required')
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


def active_routing_policy(bundle=PREVIOUS_BUNDLE):
    """Rebuild the board's active policy exactly as r4's launch published it."""
    from cochem_pipeline.catalog_activation import compile_change
    from cochem_pipeline.routing import load_routing_policy
    bundle = Path(bundle)
    raw = read_regular(bundle / 'launch-manifest.json', maximum=1024 * 1024)
    if sha(raw) != PREVIOUS_LAUNCH_SHA256:
        raise ValueError('Active catalog bundle manifest differs from its pin')
    launch = _strict_json(raw.decode('utf-8'))
    if (launch.get('baseline_policy_digest') != BASELINE_POLICY_DIGEST
            or launch.get('catalog_policy_digest') != ACTIVE_POLICY_DIGEST):
        raise ValueError('Active catalog bundle does not publish the reviewed policy')
    rows = {row['name']: row for row in launch['files']}
    config = read_regular(bundle / 'pipeline.json')
    proposal_raw = read_regular(bundle / 'proposal.json')
    for name, data in (('pipeline.json', config), ('proposal.json', proposal_raw)):
        if sha(data) != rows[name]['sha256'] or len(data) != rows[name]['length']:
            raise ValueError('Active catalog bundle input differs from its manifest')
    if sha(config) != PREVIOUS_CONFIG_SHA256 or sha(proposal_raw) != launch.get('proposal_sha256'):
        raise ValueError('Active catalog baseline or proposal differs from its pins')
    baseline = load_routing_policy(_strict_json(config.decode('utf-8'))['routing'])
    proposal = _strict_json(proposal_raw.decode('utf-8'))
    if (baseline.digest != BASELINE_POLICY_DIGEST or proposal.get('schema') != 'cochem-catalog-change-request/1'
            or proposal.get('previous_policy_digest') != BASELINE_POLICY_DIGEST):
        raise ValueError('Active catalog proposal does not extend the reviewed baseline')
    policy = compile_change(baseline, proposal['catalog'], expected_policy_digest=BASELINE_POLICY_DIGEST).policy
    if policy.digest != ACTIVE_POLICY_DIGEST:
        raise ValueError('Rebuilt policy differs from the board-active digest')
    basis = dict(schema='cochem-428-catalog-request-basis/1', active_bundle_launch_manifest_sha256=sha(raw),
        baseline_policy_digest=BASELINE_POLICY_DIGEST, active_policy_digest=ACTIVE_POLICY_DIGEST,
        proposal_sha256=sha(proposal_raw), baseline_config_sha256=sha(config))
    return policy, basis


def codex_effort_contracts(binding, targets):
    """Reviewed Codex selectors pinned to the exact bound binary and version."""
    if not isinstance(binding, dict) or not re.fullmatch('[a-f0-9]{64}', str(binding.get('sha256', ''))):
        raise ValueError('Codex effort contracts need the exact reviewed binary binding')
    contracts = {}
    for model, effort in sorted(targets):
        contracts[f'{model}:{effort}'] = dict(arguments=['-c', 'model_reasoning_effort=' + json.dumps(effort)],
            version_arguments=['--version'], executable_sha256=binding['sha256'], version=binding['version'],
            capability_reference=CODEX_CAPABILITY_REFERENCE, thinking_enabled=None, native_metadata=None)
    return contracts


def route_active_policy(candidate, policy, binary_bindings, catalog):
    """r6 boots on the board-active policy that its catalog phase publishes.

    Only the provider entries that policy makes invalid change: the retired
    Gemini binding and its effort contract leave, and Codex gains reviewed
    effort contracts (for every routed or catalog Codex target) so its probes
    record the same exact binary/version/effort evidence as Claude and Agy.
    """
    candidate = deepcopy(candidate)
    candidate['routing'] = policy.as_dict()
    providers = candidate['providers']
    for name, binding in binary_bindings.items():
        if providers[name].get('executable') != binding['executable']:
            raise ValueError('Bootstrap provider executable differs from its reviewed binding')
    routed = {}
    for pairs in policy.as_dict()['tiers'].values():
        for pair in pairs:
            routed.setdefault(pair['provider'], set()).add((pair['model'], pair['reasoning_effort']))
    gemini = providers['gemini']
    routed_gemini = {model if effort is None else f'{model}:{effort}' for model, effort in routed.get('gemini', ())}
    retired = set(gemini.get('model_bindings', {})) - routed_gemini
    if retired != RETIRED_GEMINI_BINDINGS:
        raise ValueError('Only the reviewed retired Gemini binding may leave the bootstrap')
    for key in sorted(retired):
        gemini['model_bindings'].pop(key)
        gemini.get('effort_contracts', {}).pop(key, None)
    codex = providers['codex']
    if 'effort_contracts' in codex:
        raise ValueError('Codex effort contracts are created only from the reviewed binding')
    targets = set(routed.get('codex', ())) | {(model['model'], model['effort'])
        for model in catalog['models'].values() if model['provider'] == 'codex'}
    if any(effort is None for _, effort in targets):
        raise ValueError('Every Codex target needs an explicit reasoning effort')
    codex['effort_contracts'] = codex_effort_contracts(binary_bindings['codex'], targets)
    for name in ('claude', 'gemini'):
        for key, contract in providers[name].get('effort_contracts', {}).items():
            if (contract['executable_sha256'] != binary_bindings[name]['sha256']
                    or contract['version'] != binary_bindings[name]['version']):
                raise ValueError('Reviewed effort contract no longer matches its bound binary: ' + name)
    return candidate


def bootstrap_from_current_428(previous_bytes, *, expected_previous_pin=PREVIOUS_CONFIG_SHA256,
                               coding_registration=None, target_root=TARGET_ROOT):
    """Only explicit bootstrap changes; no provider/model/quota authority invented."""
    if sha(previous_bytes) != expected_previous_pin:
        raise ValueError('Current-r4 configuration differs from reviewed pin')
    if target_root not in {root for root, _ in RELEASES.values()}:
        raise ValueError('Unknown operational target root')
    previous = _strict_json(previous_bytes.decode('utf-8'))
    if previous.get('runtime_version') != '4.2.8' or previous.get('max_execution_slots') != 4:
        raise ValueError('Upgrade requires current 4.2.8 and four shared execution slots')
    candidate = deepcopy(previous)
    for key in ('source_root', 'wiki_root', 'manifest_path'):
        path = candidate.get('knowledge', {}).get(key)
        if not isinstance(path, str) or not path.startswith(PREVIOUS_ROOT + '\\source\\knowledge\\'):
            raise ValueError('Current-r4 knowledge source binding differs')
        candidate['knowledge'][key] = target_root + path[len(PREVIOUS_ROOT):]
    candidate['catalog_activation'] = True
    candidate['task_planning'] = None
    if coding_registration is not None:
        from cochem_pipeline.project_registration import RegistrationPolicy
        RegistrationPolicy.from_dict(coding_registration)
        candidate['coding_registration'] = deepcopy(coding_registration)
    # Everything else, including actual native selector contracts, old project
    # definitions, pools, credentials, repair budgets and knowledge DBs stays put.
    return candidate


def require_committed_tree(repository, commit, paths=('src', 'scripts')):
    """Offline preparation executes working-tree code (request compilation,
    contract checks, bootstrap transforms); it must be the packaged commit's.
    An empty paths tuple checks the whole tree. Index flags that hide edits
    (assume-unchanged, skip-worktree) and ignored non-cache files are refused."""
    if not isinstance(commit, str) or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('An exact packaged source commit is required')
    spec = ['--', *paths] if paths else []
    def git(*args):
        return subprocess.run(['git', '-C', str(repository), *args], capture_output=True, timeout=120)
    diff = git('diff', '--quiet', commit, *spec)
    untracked = git('ls-files', '--others', '--exclude-standard', *spec)
    flags = git('ls-files', '-v', *spec)
    ignored = git('ls-files', '--others', '--ignored', '--exclude-standard', '--',
                  *(paths or ('src', 'scripts', 'pipeline_tests', 'conftest.py', 'pytest.ini')))
    hidden = [line for line in flags.stdout.decode('utf-8', 'replace').splitlines()
              if line[:1].islower() or line[:1] == 'S']
    shadow = [line for line in ignored.stdout.decode('utf-8', 'replace').splitlines()
              if line.strip() and '__pycache__/' not in line and not line.endswith('.pyc')]
    if (any(result.returncode != 0 for result in (diff, untracked, flags, ignored))
            or untracked.stdout.strip() or hidden or shadow):
        raise ValueError('Working-tree source or scripts differ from the packaged commit')


def require_checkout(repository):
    """The packaged checkout must be the one whose code this process runs."""
    import cochem_pipeline
    if (Path(repository).resolve() != SCRIPTS.parent.resolve()
            or Path(cochem_pipeline.__file__).resolve().parent != (SCRIPTS.parent / 'src' / 'cochem_pipeline').resolve()):
        raise ValueError('Preparation must run from, and import, the packaged checkout')


def _committed_script(repository, commit, name):
    raw = read_regular(Path(repository)/'scripts'/name)
    committed = subprocess.run(['git', '-C', str(repository), 'show', commit+':scripts/'+name],
                               capture_output=True, check=True, timeout=15).stdout
    # Git may normalize working checkout line endings; package committed bytes.
    if raw.replace(b'\r\n', b'\n') != committed.replace(b'\r\n', b'\n'):
        raise ValueError('Release script differs from the frozen source commit: '+name)
    return committed


SOURCE_TEST_SCHEMA = 'cochem-428-operational-source-tests/1'
# The focused catalog-phase, launcher, preparer and effort suites every fresh
# payload must have passed (scripts/record_source_tests_428.py).
REQUIRED_SOURCE_TEST_MODULES = frozenset('pipeline_tests/' + name for name in (
    'test_operational_launch_428.py', 'test_operational_fence_cleanup_428.py', 'test_operational_recovery_428.py',
    'test_operational_recovery_package_428.py', 'test_operational_fence_diagnostic_428.py',
    'test_operational_process_roles_428.py', 'test_operational_observer_roles_428.py',
    'test_operational_observer_acl_428.py', 'test_operational_release_428.py', 'test_owner_admission_fence_428.py',
    'test_owner_task_catalog_428.py', 'test_operational_preserved_pid_428.py', 'test_operational_running_recovery_428.py',
    'test_operational_oneshot_identity_428.py', 'test_operational_catalog_request_428.py',
    'test_operational_release_r6_428.py', 'test_task_catalog_acceptance_428.py', 'test_catalog_phase_e2e_428.py',
    'test_codex_effort_contract_428.py', 'test_native_effort.py', 'test_native_effort_v3.py', 'test_worker_contract.py',
    'test_worker_inference_policy.py', 'test_codex_integration_428.py', 'test_task_catalog_428.py',
    'test_acceptance_428.py', 'test_worker_gemini_dispatch.py', 'test_output_contracts_428.py'))


def read_source_test_evidence(path, source_commit):
    """A PASSED serialized source-test report for the exact packaged commit."""
    raw = read_regular(Path(path), maximum=1024 * 1024)
    value = _strict_json(raw.decode('utf-8'))
    expected = dict(schema=SOURCE_TEST_SCHEMA, source_commit=source_commit,
        runner='scripts/run_source_tests_428.py', status='PASSED', failed=0, host_acceptance_executed=False)
    if (not isinstance(value, dict) or set(value) != set(expected) | {'passed', 'modules', 'source_test_report_sha256'}
            or any(type(value.get(key)) is not type(want) or value[key] != want for key, want in expected.items())
            or type(value['passed']) is not int or not 1 <= value['passed'] <= 100000
            or not isinstance(value['modules'], list) or not value['modules']
            or any(not isinstance(item, str) or not re.fullmatch(r'pipeline_tests/test_[a-z0-9_]+\.py', item)
                   for item in value['modules'])
            or not REQUIRED_SOURCE_TEST_MODULES <= set(value['modules'])
            or not re.fullmatch('[a-f0-9]{64}', str(value['source_test_report_sha256']))):
        raise ValueError('Source-test evidence is not a PASSED report for the packaged commit')
    # scripts/record_source_tests_428.py keeps the runner report beside it.
    report = Path(path).with_name('source-tests.log')
    if not report.is_file() or sha(read_regular(report, maximum=64 * 1024 * 1024)) != value['source_test_report_sha256']:
        raise ValueError('Source-test evidence is not a PASSED report for the packaged commit (report missing or changed)')
    return raw


def prepare_operational_release_428(freeze, wheelhouse, application, destination, repository, *,
                                    previous_bundle=PREVIOUS_BUNDLE, coding_registration=None,
                                    release='r5', binary_bindings=None, catalog=None, source_test_evidence=None):
    """r5 reproduces the spent 865a29b recipe; r6 additionally routes the
    board-active policy and requires a PASSED source-test report."""
    if release not in RELEASES:
        raise ValueError('Unknown operational release')
    target_root, revision = RELEASES[release]
    if (release == 'r6') != (binary_bindings is not None and catalog is not None and source_test_evidence is not None):
        raise ValueError('Release r6 (only) requires binary bindings, the task catalog and PASSED source tests')
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
    candidate = bootstrap_from_current_428(previous_raw, coding_registration=coding_registration,
                                           target_root=target_root)
    routing_basis = evidence_raw = None
    if release == 'r6':
        require_checkout(repository)
        require_committed_tree(repository, source['commit'])
        # The catalog that sizes the Codex contracts is the packaged one.
        if catalog != _strict_json(read_regular(freeze / 'docs/4.2.8/routing-candidate.json').decode('utf-8')):
            raise ValueError('Task catalog differs from the packaged commit routing candidate')
        policy, routing_basis = active_routing_policy(previous_bundle)
        candidate = route_active_policy(candidate, policy, binary_bindings, catalog)
        evidence_raw = read_source_test_evidence(source_test_evidence, source['commit'])
    scripts = {name: _committed_script(repository, source['commit'], name) for name in (INSTALLER, COPY_HELPER)}
    if release == 'r6' and (f"'{target_root.rsplit(chr(92), 1)[1]}'".encode() not in scripts[INSTALLER]
                            or f"'{revision}'".encode() not in scripts[INSTALLER]
                            or b'20261015' in scripts[INSTALLER]):
        raise ValueError('Packaged installer does not install this release root and revision')
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
                or alignment['status'] != 'VERSION_ALIGNMENT_VERIFIED'
                or (release == 'r6' and parsed.routing.digest != ACTIVE_POLICY_DIGEST)):
            raise ValueError('Operational bootstrap configuration failed validation')
        add('pipeline.json', destination/'pipeline.json', sha(config_raw), len(config_raw))
        req = write('runtime-requirements.txt', ('\n'.join(requirements)+'\n').encode('utf-8'))
        add('wheels/runtime-requirements.txt', destination/'runtime-requirements.txt', sha(req), len(req))
        if evidence_raw is not None:
            evidence_pin = sha(write('source-test-evidence.json', evidence_raw))
        else:
            evidence = dict(schema='cochem-428-source-test-evidence/1', version='4.2.8',
                source_commit=source['commit'], source_manifest_sha256=sha(source_raw),
                validation_doc_sha256=sha(read_regular(freeze/'docs/4.2.8/VALIDATION.md')),
                runner='scripts/run_source_tests_428.py', tests_executed_by_preparer=False,
                host_acceptance_executed=False)
            evidence_pin = sha(write('source-test-evidence.json', evidence))
        manifest = dict(schema='cochem-428-install-bundle/1', host='AETHERDESK', revision=revision,
            version='4.2.8', source_commit=source['commit'], source_test_evidence_sha256=evidence_pin,
            files=files, activation_ready=False)
        install_pin = sha(write('install-manifest.json', manifest))
        for name, raw in scripts.items():
            write(name, raw)
        metadata = dict(schema='cochem-428-operational-release/1', version='4.2.8', revision=revision,
            previous=baseline, target_root=target_root, source_commit=source['commit'],
            install_manifest_sha256=install_pin, bootstrap_candidate_sha256=sha(config_raw),
            source_test_evidence_sha256=evidence_pin, task_planning_enabled=False,
            catalog_publication_required=True, coding_registration=candidate.get('coding_registration'),
            files=[dict(name=name, sha256=sha(read_regular(destination/name)), length=(destination/name).stat().st_size)
                   for name in (INSTALLER, COPY_HELPER, 'pipeline.json', 'install-manifest.json',
                                'source-test-evidence.json', 'runtime-requirements.txt')],
            stale_recovery_included=False, input_window_minutes=20, late_prompts=False,
            owner_entrypoint_included=False, actual_host_verified=False, activation_ready=False)
        if release == 'r6':
            metadata.update(release='r6', routing_basis=routing_basis, bootstrap_policy_digest=ACTIVE_POLICY_DIGEST,
                            retired_gemini_bindings=sorted(RETIRED_GEMINI_BINDINGS),
                            codex_effort_contracts=len(candidate['providers']['codex']['effort_contracts']))
        release_pin = sha(write('operational-release.json', metadata))
        result = dict(schema='cochem-428-operational-package-preparation/1',
            status='OFFLINE_OPERATIONAL_PAYLOAD_PREPARED', destination=str(destination),
            target_root=target_root, revision=revision, source_commit=source['commit'], payload_files=len(files),
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
    parser.add_argument('--release', choices=sorted(RELEASES), required=True)
    parser.add_argument('--binary-bindings', type=Path)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--source-test-evidence', type=Path)
    args = parser.parse_args()
    def read_json(path):
        return _strict_json(read_regular(path).decode('utf-8')) if path else None
    print(json.dumps(prepare_operational_release_428(args.freeze, args.wheelhouse, args.application,
        args.destination, args.repository, previous_bundle=args.previous_bundle,
        coding_registration=read_json(args.coding_registration), release=args.release,
        binary_bindings=read_json(args.binary_bindings), catalog=read_json(args.catalog),
        source_test_evidence=args.source_test_evidence), indent=2))


if __name__ == '__main__':
    main()
