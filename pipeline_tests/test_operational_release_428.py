"""Offline release preparation fixtures; no builds, providers, or installer execution."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline_tests.test_release_bundle_428 import _make_bundle_fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('operational_release_428', ROOT/'scripts/prepare_operational_release_428.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def baseline():
    return dict(runtime_version='4.2.8', max_execution_slots=4, catalog_activation=True,
        knowledge=dict(source_root=release.PREVIOUS_ROOT+r'\source\knowledge\.sources',
            wiki_root=release.PREVIOUS_ROOT+r'\source\knowledge\wiki',
            manifest_path=release.PREVIOUS_ROOT+r'\source\knowledge\v4.1.2_manifest.json',
            state_root=r'C:\ProgramData\CoChemPipeline427\private\knowledge-existing'),
        providers={'gemini':{'executable':'unchanged', 'effort_contracts':{'existing':{'sha256':'a'*64}}}},
        workers={'slot1':{'credential_target':'existing'}}, slot_roots={'slot1':'existing'},
        private_root='existing-private', token_file='existing-token-path',
        ramdisk={'mount_root':'R:\\'}, routing={'existing_budget':17},
        coding_projects={'windows-acceptance':{'repository':'fixture'},'exam':{'repository':'specialist-owned'}})


def raw(value):
    return (json.dumps(value)+'\n').encode()


def test_candidate_moves_only_knowledge_source_and_disables_planning():
    previous = baseline()
    previous['task_planning'] = {'catalog_file':'old-pinned-authority'}
    blob = raw(previous)
    new = release.bootstrap_from_current_428(blob, expected_previous_pin=release.sha(blob))
    assert new['task_planning'] is None
    assert new['catalog_activation'] is True
    for key in previous.keys() - {'knowledge','task_planning','catalog_activation'}:
        assert new[key] == previous[key]
    assert new['knowledge']['state_root'] == previous['knowledge']['state_root']
    assert new['knowledge']['source_root'].startswith(release.TARGET_ROOT+'\\')


@pytest.mark.parametrize('change', ['pin','version','slots','knowledge'])
def test_old_r6_or_changed_baseline_refused(change):
    value = baseline()
    if change == 'version': value['runtime_version'] = '4.2.7'
    if change == 'slots': value['max_execution_slots'] = 6
    if change == 'knowledge': value['knowledge']['wiki_root'] = r'C:\different\wiki'
    blob = raw(value)
    with pytest.raises(ValueError):
        release.bootstrap_from_current_428(blob, expected_previous_pin='0'*64 if change=='pin' else release.sha(blob))


def test_reviewed_registration_is_explicit_and_preserves_existing_projects():
    blob = raw(baseline())
    reviewed = {'source_roots':[r'C:\Users\ansac\source\repos']}
    new = release.bootstrap_from_current_428(blob, expected_previous_pin=release.sha(blob), coding_registration=reviewed)
    assert new['coding_registration'] == reviewed
    assert new['coding_projects'] == baseline()['coding_projects']
    with pytest.raises(ValueError, match='synchronized'):
        release.bootstrap_from_current_428(blob, expected_previous_pin=release.sha(blob),
                                          coding_registration={'source_roots':[r'D:\Gdrive\repos']})


@pytest.fixture
def package(tmp_path, monkeypatch):
    args = _make_bundle_fixture(tmp_path, monkeypatch)
    args.pop('previous_config')
    args.pop('expected_previous_pin')
    blob = raw(baseline())
    monkeypatch.setattr(release, 'read_current_baseline', lambda path: (blob, {'actual_host_verified':False}))
    original = release.bootstrap_from_current_428
    monkeypatch.setattr(release, 'bootstrap_from_current_428',
        lambda value, **kwargs: original(value, expected_previous_pin=release.sha(blob), **kwargs))
    monkeypatch.setattr(release, '_committed_script', lambda repo, commit, name: (repo/'scripts'/name).read_bytes())
    monkeypatch.setattr(release, 'load_config', lambda _: SimpleNamespace(max_execution_slots=4,
        task_planning=None, catalog_activation=True))
    monkeypatch.setattr(release, 'verify_version_alignment', lambda _: {'status':'VERSION_ALIGNMENT_VERIFIED'})
    return args


def test_new_bundle_is_bootstrap_only_exact_fixed_r5_and_has_no_old_launcher(package):
    result = release.prepare_operational_release_428(**package)
    bundle = package['destination']
    metadata = json.loads((bundle/'operational-release.json').read_text())
    install = json.loads((bundle/'install-manifest.json').read_text())
    assert result['target_root'] == release.TARGET_ROOT
    assert install['revision'] == release.REVISION
    assert result['administrator_launch_ready'] is False
    assert metadata['catalog_publication_required'] is True
    assert metadata['task_planning_enabled'] is False
    assert metadata['actual_host_verified'] is False
    assert not any((bundle/name).exists() for name in ('run_428_launch.ps1','run_r6_launch.ps1','proposal.json','pointer.json'))
    for row in metadata['files']:
        assert release.sha((bundle/row['name']).read_bytes()) == row['sha256']
    for row in install['files']:
        assert release.sha(Path(row['source']).read_bytes()) == row['sha256']
    assert (bundle/release.INSTALLER).read_bytes() == (ROOT/'scripts'/release.INSTALLER).read_bytes()
    source_evidence = json.loads((bundle/'source-test-evidence.json').read_text())
    assert source_evidence['tests_executed_by_preparer'] is False


@pytest.mark.parametrize('mutation', ['source','wheel','app_commit','lock','duplicate','old_helper'])
def test_tampered_payloads_refuse_before_destination(package, monkeypatch, mutation):
    if mutation == 'source': (package['freeze']/'README.md').write_bytes(b'changed')
    if mutation == 'wheel': next(package['wheelhouse'].glob('*.whl')).write_bytes(b'changed')
    if mutation == 'lock': (package['freeze']/'uv.lock').write_bytes(b'changed')
    if mutation == 'app_commit':
        app = json.loads(package['application'].read_text())
        app['source_commit'] = 'b'*40
        package['application'].write_text(json.dumps(app))
    if mutation == 'duplicate':
        manifest = package['freeze']/'source-preparation.json'
        value = json.loads(manifest.read_text())
        value['files'].append(deepcopy(value['files'][0]))
        manifest.write_text(json.dumps(value))
    if mutation == 'old_helper':
        monkeypatch.setattr(release, 'COPY_HELPER_SHA256', '0'*64)
    with pytest.raises(ValueError):
        release.prepare_operational_release_428(**package)
    assert not package['destination'].exists()


def test_invalid_bootstrap_preserves_partial_package_evidence(package, monkeypatch):
    monkeypatch.setattr(release, 'load_config', lambda _: SimpleNamespace(max_execution_slots=6,
        task_planning=None, catalog_activation=True))
    with pytest.raises(ValueError, match='bootstrap'):
        release.prepare_operational_release_428(**package)
    held = json.loads((package['destination']/'package-held.json').read_text())
    assert held['status'] == 'HELD_PRESERVE_PARTIAL'
    assert held['automatic_retry'] is False


def test_existing_package_never_reused(package):
    package['destination'].mkdir()
    marker = package['destination']/'owner-evidence'
    marker.write_text('preserve')
    with pytest.raises(ValueError, match='fresh'):
        release.prepare_operational_release_428(**package)
    assert marker.read_text() == 'preserve'


def test_saved_baseline_validates_all_reviewed_pins(tmp_path, monkeypatch):
    config = raw(baseline())
    config_pin = release.sha(config)
    install = raw(dict(source_commit=release.PREVIOUS_COMMIT,
        files=[dict(relative='pipeline.json',sha256=config_pin,length=len(config))]))
    launch = raw(dict(source_commit=release.PREVIOUS_COMMIT,candidate_sha256=config_pin,
        install_manifest_sha256=release.sha(install),revision='windows-20261014-428-v4'))
    for name, data in [('pipeline.json',config),('install-manifest.json',install),('launch-manifest.json',launch)]:
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(release, 'PREVIOUS_CONFIG_SHA256', config_pin)
    monkeypatch.setattr(release, 'PREVIOUS_INSTALL_SHA256', release.sha(install))
    monkeypatch.setattr(release, 'PREVIOUS_LAUNCH_SHA256', release.sha(launch))
    data, evidence = release.read_current_baseline(tmp_path)
    assert data == config and evidence['actual_host_verified'] is False
    (tmp_path/'pipeline.json').write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        release.read_current_baseline(tmp_path)
