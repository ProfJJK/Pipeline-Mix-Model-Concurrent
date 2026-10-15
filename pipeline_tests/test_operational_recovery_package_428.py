"""Offline ordinary temp-file packaging; no provider, installer or host action."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('operational_recovery', ROOT / 'scripts/prepare_operational_recovery_428.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def encoded(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def repin(package, monkeypatch):
    original = package['original_launch']
    raw = (original / 'launch-manifest.json').read_bytes()
    monkeypatch.setattr(prepare, 'ORIGINAL_LAUNCH_SHA256', prepare.sha(raw))


@pytest.fixture
def package(tmp_path, monkeypatch):
    original = tmp_path / 'original'; original.mkdir()
    repository = tmp_path / 'repo'; (repository / 'scripts').mkdir(parents=True)
    launcher = b'function Assert-OpRecoveryManifest { }\n# exact committed recovery source\n'
    (repository / 'scripts' / prepare.LAUNCHER).write_bytes(launcher)
    monkeypatch.setattr(prepare, '_committed_script', lambda repo, commit, name: launcher)
    payload = tmp_path / 'payload'; payload.mkdir()
    (payload / 'source.txt').write_bytes(b'immutable original runtime payload')
    files = {'pipeline.json': b'{"runtime_version":"4.2.8"}',
             'source-test-evidence.json': b'{"original_runtime_test_evidence":true}',
             'task-catalog-request.json': b'{"request":"original"}',
             'task-catalog-manifest.json': b'{"manifest":"original"}',
             'codex-integration.json': b'{"integration":"original"}',
             'operational-release.json': b'{"release":"original"}',
             'reviewed_428_launch_helpers.ps1': b'# original pure helpers',
             'install_operational_428_runtime.ps1': b'# original installer is never executed',
             'stage_aetherdesk_427_payloads.ps1': b'# original copier',
             'runtime-requirements.txt': b'original requirements',
             prepare.LAUNCHER: b'# spent original launcher'}
    install = dict(schema='cochem-428-install-bundle/1', version='4.2.8', revision=prepare.REVISION,
                   source_commit=prepare.RUNTIME_SOURCE_COMMIT,
                   source_test_evidence_sha256=prepare.sha(files['source-test-evidence.json']),
                   files=[dict(relative='source/source.txt', source=str(payload / 'source.txt'),
                               sha256=prepare.sha((payload / 'source.txt').read_bytes()),
                               length=(payload / 'source.txt').stat().st_size)])
    files['install-manifest.json'] = encoded(install)
    for name, raw in files.items():
        (original / name).write_bytes(raw)
    manifest = dict(schema='cochem-428-operational-launch/1', revision=prepare.REVISION,
        source_commit=prepare.RUNTIME_SOURCE_COMMIT, previous_root=prepare.PREVIOUS_ROOT,
        target_root=prepare.TARGET_ROOT, previous_config_sha256=prepare.PREVIOUS_CONFIG_SHA256,
        previous_install_sha256=prepare.PREVIOUS_INSTALL_SHA256,
        install_manifest_sha256=prepare.sha(files['install-manifest.json']),
        bootstrap_sha256=prepare.sha(files['pipeline.json']), request_sha256=prepare.sha(files['task-catalog-request.json']),
        request_id='b' * 32, catalog_timeout_seconds=7200, integration_manifest='codex-integration.json',
        integration_sha256=prepare.sha(files['codex-integration.json']), input_window_minutes=20,
        late_prompts=False, pending_backlog_allowed=True,
        files=[dict(name=name, length=len(raw), sha256=prepare.sha(raw)) for name, raw in sorted(files.items())])
    (original / 'launch-manifest.json').write_bytes(encoded(manifest))
    evidence = tmp_path / 'recovery-tests.json'
    evidence.write_bytes(encoded(dict(schema='cochem-428-operational-recovery-source-tests/1',
        launcher_source_commit='c' * 40, runtime_source_commit=prepare.RUNTIME_SOURCE_COMMIT,
        runner='scripts/run_source_tests_428.py', status='PASSED', passed=10, failed=0,
        host_acceptance_executed=False, source_test_report_sha256='d' * 64)))
    result = dict(original_launch=original, destination=tmp_path / 'recovery', repository=repository,
        launcher_source_commit='c' * 40, recovery_source_tests=evidence,
        recovery_source_tests_sha256=prepare.sha(evidence.read_bytes()), recovery_id='e' * 32)
    repin(result, monkeypatch)
    return result


def test_exact_original_inputs_preserved_and_launcher_provenance_separate(package):
    original = {p.name: p.read_bytes() for p in package['original_launch'].iterdir()}
    result = prepare.prepare_operational_recovery(**package)
    destination = package['destination']
    manifest = json.loads((destination / 'launch-manifest.json').read_bytes())
    old = json.loads(original['launch-manifest.json'])
    assert {k: v for k, v in manifest.items() if k in old and k != 'files'} == {k: v for k, v in old.items() if k != 'files'}
    assert manifest['source_commit'] == prepare.RUNTIME_SOURCE_COMMIT
    assert manifest['launcher_source_commit'] == package['launcher_source_commit']
    assert manifest['recovery_manifest'] == 'admission-recovery.json'
    assert manifest['recovery_sha256'] == prepare.sha((destination / 'admission-recovery.json').read_bytes())
    for row in manifest['files']:
        raw = (destination / row['name']).read_bytes()
        assert row['sha256'] == prepare.sha(raw) and row['length'] == len(raw)
    for row in old['files']:
        if row['name'] != prepare.LAUNCHER:
            assert row in manifest['files']
            assert (destination / row['name']).read_bytes() == original[row['name']]
    assert (destination / 'original-launch-manifest.json').read_bytes() == original['launch-manifest.json']
    assert (destination / prepare.LAUNCHER).read_bytes() == (package['repository'] / 'scripts' / prepare.LAUNCHER).read_bytes()
    assert {p.name: p.read_bytes() for p in package['original_launch'].iterdir()} == original
    assert result['host_executed'] is False and result['native_acceptance_executed'] is False
    assert result['source_tests_executed_by_preparer'] is False
    assert result['launch_manifest_sha256'] == prepare.sha((destination / 'launch-manifest.json').read_bytes())


@pytest.mark.parametrize('mutation', ['manifest_hash', 'input', 'nested_input', 'source', 'late_prompt', 'missing_file',
    'duplicate', 'case_alias', 'unsafe_name', 'reserved_name', 'nested_relative', 'nested_source', 'length_bool',
    'existing_destination', 'gdrive', 'relative_destination', 'bad_launcher_commit', 'old_launcher',
    'evidence_pin', 'evidence_commit', 'evidence_host_claim', 'evidence_failed', 'evidence_schema'])
def test_invalid_inputs_rejected_before_any_destination_write(package, monkeypatch, mutation):
    original = package['original_launch']
    manifest = json.loads((original / 'launch-manifest.json').read_bytes())
    if mutation == 'manifest_hash':
        monkeypatch.setattr(prepare, 'ORIGINAL_LAUNCH_SHA256', '0' * 64)
    elif mutation == 'input':
        (original / 'pipeline.json').write_bytes(b'changed')
    elif mutation == 'nested_input':
        (original.parent / 'payload' / 'source.txt').write_bytes(b'changed')
    elif mutation in ('source', 'late_prompt', 'missing_file', 'duplicate', 'case_alias', 'unsafe_name', 'reserved_name', 'length_bool'):
        if mutation == 'source': manifest['source_commit'] = '0' * 40
        elif mutation == 'late_prompt': manifest['late_prompts'] = True
        elif mutation == 'missing_file': manifest['files'] = [r for r in manifest['files'] if r['name'] != prepare.LAUNCHER]
        elif mutation == 'duplicate': manifest['files'].append(manifest['files'][0])
        elif mutation == 'case_alias': manifest['files'].append(dict(manifest['files'][0], name=manifest['files'][0]['name'].upper()))
        elif mutation == 'unsafe_name': manifest['files'][0]['name'] = '../escape'
        elif mutation == 'reserved_name': manifest['files'][0]['name'] = 'original-launch-manifest.json'
        else: manifest['files'][0]['length'] = True
        (original / 'launch-manifest.json').write_bytes(encoded(manifest)); repin(package, monkeypatch)
    elif mutation in ('nested_relative', 'nested_source'):
        install = json.loads((original / 'install-manifest.json').read_bytes())
        install['files'][0]['relative' if mutation == 'nested_relative' else 'source'] = '../escape'
        raw = encoded(install); (original / 'install-manifest.json').write_bytes(raw)
        manifest['install_manifest_sha256'] = prepare.sha(raw)
        manifest['files'] = [dict(r, sha256=prepare.sha(raw), length=len(raw)) if r['name'] == 'install-manifest.json' else r for r in manifest['files']]
        (original / 'launch-manifest.json').write_bytes(encoded(manifest)); repin(package, monkeypatch)
    elif mutation == 'existing_destination':
        package['destination'].mkdir(); (package['destination'] / 'preserved').write_bytes(b'preserve')
    elif mutation == 'gdrive':
        root = original.parent / 'GDrive'; root.mkdir(); package['destination'] = root / 'recovery'
    elif mutation == 'relative_destination': package['destination'] = Path('relative-recovery')
    elif mutation == 'bad_launcher_commit': package['launcher_source_commit'] = 'HEAD'
    elif mutation == 'old_launcher': monkeypatch.setattr(prepare, '_committed_script', lambda *args: b'# no reviewed recovery entrypoint')
    elif mutation == 'evidence_pin': package['recovery_source_tests_sha256'] = '0' * 64
    else:
        path = package['recovery_source_tests']; evidence = json.loads(path.read_bytes())
        if mutation == 'evidence_commit': evidence['launcher_source_commit'] = '0' * 40
        elif mutation == 'evidence_host_claim': evidence['host_acceptance_executed'] = True
        elif mutation == 'evidence_failed': evidence['failed'] = 1
        else: evidence['schema'] = 'ordinary-diagnostic-is-not-authority'
        path.write_bytes(encoded(evidence)); package['recovery_source_tests_sha256'] = prepare.sha(path.read_bytes())
    with pytest.raises((ValueError, OSError)):
        prepare.prepare_operational_recovery(**package)
    if mutation == 'existing_destination':
        assert [p.name for p in package['destination'].iterdir()] == ['preserved']
    else:
        assert not package['destination'].exists()


def test_recovery_contract_is_exact_fixed_reviewed_evidence():
    recovery = prepare.make_recovery_spec('c' * 40, recovery_id='e' * 32)
    assert recovery['fence']['nonce'] == 'a232264b12984ff2ab9ef33b7ec24c75'
    assert recovery['warden']['last_run_utc'] == '2026-10-15T01:37:07Z'
    assert recovery['fence']['last_run_utc'] == '2026-10-15T18:41:18Z'
    prepare.validate_recovery_spec(recovery)
    for key in ('original_sitting', 'install_after_sha256', 'baseline_sha256', 'owner_result_sha256'):
        altered = deepcopy(recovery); altered[key] = 'unreviewed'
        with pytest.raises(ValueError): prepare.validate_recovery_spec(altered)
    altered = deepcopy(recovery); altered['warden']['pid'] += 1
    with pytest.raises(ValueError): prepare.validate_recovery_spec(altered)
    altered = deepcopy(recovery); altered['diagnostic_path'] = 'not-authority.json'
    with pytest.raises(ValueError): prepare.validate_recovery_spec(altered)


def test_changed_worktree_launcher_cannot_claim_chosen_commit(package, monkeypatch):
    from scripts.prepare_operational_release_428 import _committed_script
    monkeypatch.setattr(prepare, '_committed_script', _committed_script)
    # Exercise the actual committed-byte verifier with an inert Git response.
    monkeypatch.setattr(_committed_script.__globals__['subprocess'], 'run',
                        lambda *args, **kwargs: SimpleNamespace(stdout=b'other committed launcher'))
    with pytest.raises(ValueError, match='frozen source commit'):
        prepare.prepare_operational_recovery(**package)
    assert not package['destination'].exists()


def test_hardlinked_original_input_is_rejected_before_writing(package):
    source = package['original_launch'] / 'pipeline.json'
    (source.parent / 'alternate-hardlink').hardlink_to(source)
    with pytest.raises(ValueError, match='links'):
        prepare.prepare_operational_recovery(**package)
    assert not package['destination'].exists()


@pytest.mark.parametrize('redirected', ['original_input', 'original_parent', 'nested_input', 'destination_parent'])
def test_redirected_paths_are_rejected_before_writing(package, monkeypatch, redirected):
    # Inert reparse metadata avoids creating any actual junction/symlink or
    # requesting Windows symlink privileges merely to test path rejection.
    path = {'original_input': package['original_launch'] / 'pipeline.json',
            'original_parent': package['original_launch'],
            'nested_input': package['original_launch'].parent / 'payload' / 'source.txt',
            'destination_parent': package['destination'].parent}[redirected]
    original = Path.lstat

    def fake_stat(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        if self == path:
            return SimpleNamespace(st_mode=value.st_mode,
                                   st_file_attributes=getattr(value, 'st_file_attributes', 0) | 0x400)
        return value

    monkeypatch.setattr(Path, 'lstat', fake_stat)
    with pytest.raises(ValueError, match='redirect'):
        prepare.prepare_operational_recovery(**package)
    assert not package['destination'].exists()


def test_generated_recovery_id_is_fresh_and_unreviewed_values_cannot_be_supplied():
    first = prepare.make_recovery_spec('c' * 40)
    second = prepare.make_recovery_spec('c' * 40)
    assert first['recovery_id'] != second['recovery_id']
    assert len(first['recovery_id']) == 32
    with pytest.raises(TypeError):
        prepare.make_recovery_spec('c' * 40, fence={'pid': 999})
