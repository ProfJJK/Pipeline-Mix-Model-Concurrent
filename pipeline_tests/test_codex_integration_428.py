"""Ordinary temporary-file integration updates; no CLI, task or provider launch."""
import json
from pathlib import Path
import pytest
from cochem_pipeline import codex_integration_428 as integration


@pytest.fixture
def prepared(tmp_path):
    home = tmp_path / 'owner'; home.mkdir()
    export = tmp_path / 'export'; export.mkdir()
    old = {'config': b'[other]\nkey="keep"\n[mcp_servers."cochem-pipeline"]\ncommand="old"\nargs=[]\n[mcp_servers.exam]\ncommand="exam"\n',
           'rules': b'# Personal rule\nKeep this\n# Codex: CoChem pipeline submissions\nOld rule\n# More personal rules\nKeep these\n',
           'skill': b'Old skill', 'metadata': b'Old metadata'}
    for key, relative in integration.FILES.items():
        target = home / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(old[key])
    rows = []
    for key, relative in integration.TEMPLATES.items():
        raw = (integration.RULE_HEADING + '\nNew scoped rules\n' if key == 'rules' else 'New ' + key).encode()
        path = export / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        rows.append(dict(path=relative, size=len(raw), sha256=integration.sha(raw)))
    (export / 'integration-manifest.json').write_text(json.dumps(dict(schema='cochem-codex-integration-export/1', source_commit='a'*40, files=rows)))
    runtime = tmp_path / 'runtime'; exe = runtime / '.venv/Scripts/python.exe'; exe.parent.mkdir(parents=True); exe.write_bytes(b'inert')
    client = home / 'client.json'; client.write_bytes(b'private token not exported')
    manifest = integration.prepare(export, home, runtime, client)
    return home, manifest, old


def test_only_managed_settings_change_and_manifest_has_no_personal_config(prepared):
    home, manifest, old = prepared
    assert 'private token' not in json.dumps(manifest)
    assert 'key="keep"' not in json.dumps(manifest)
    result = integration.apply(manifest)
    raw = (home / integration.FILES['config']).read_bytes()
    assert raw.startswith(b'[other]\nkey="keep"\n')
    assert raw.endswith(b'[mcp_servers.exam]\ncommand="exam"\n')
    rules = (home / integration.FILES['rules']).read_text()
    assert rules.startswith('# Personal rule\nKeep this\n')
    assert rules.endswith('# More personal rules\nKeep these\n')
    assert result['current_session_tools_loaded'] is False
    for key, value in old.items():
        assert (Path(result['backup_root']) / (key + '.original')).read_bytes() == value


def test_read_only_preflight_validates_targets_and_rechecks_drift_at_apply(prepared):
    home, manifest, old = prepared
    result = integration.verify_plan(manifest)
    assert result['status'] == 'CODEX_UPDATE_PLAN_VERIFIED'
    assert result['files_changed'] == 0
    assert all((home / integration.FILES[key]).read_bytes() == value for key, value in old.items())
    assert not list((home / '.codex').glob('pipeline-integration-backup-*'))
    target = home / integration.FILES['metadata']
    target.write_bytes(b'Late specialist edit')
    for operation in (integration.verify_plan, integration.apply):
        with pytest.raises(ValueError, match='changed since preparation'):
            operation(manifest)
    assert target.read_bytes() == b'Late specialist edit'
    assert (home / integration.FILES['config']).read_bytes() == old['config']


def test_changed_settings_hold_before_any_write(prepared):
    home, manifest, old = prepared
    target = home / integration.FILES['metadata']; target.write_bytes(b'New specialist edit')
    with pytest.raises(ValueError, match='changed since preparation'):
        integration.apply(manifest)
    assert (home / integration.FILES['config']).read_bytes() == old['config']
    assert target.read_bytes() == b'New specialist edit'
    assert not list((home / '.codex').glob('pipeline-integration-backup-*'))


def test_failed_replacement_restores_only_its_own_changes(prepared):
    home, manifest, old = prepared
    calls = []
    def fail_metadata(source, destination):
        calls.append(destination)
        if destination == home / integration.FILES['metadata']:
            raise OSError('inert failure')
        integration.os.replace(source, destination)
    with pytest.raises(OSError, match='inert failure'):
        integration.apply(manifest, replace=fail_metadata)
    assert all((home / integration.FILES[key]).read_bytes() == value for key, value in old.items())
    assert len(list((home / '.codex').glob('pipeline-integration-backup-*/held.json'))) == 1


def test_concurrent_missing_file_does_not_abort_other_file_recovery(prepared):
    home, manifest, old = prepared
    removed = home / integration.FILES['rules']
    def fail_metadata(source, destination):
        if destination == home / integration.FILES['metadata']:
            removed.unlink()  # Simulate an unrelated editor's concurrent delete.
            raise OSError('original replacement failure')
        integration.os.replace(source, destination)
    with pytest.raises(OSError, match='original replacement failure'):
        integration.apply(manifest, replace=fail_metadata)
    assert not removed.exists()
    for key in ('config', 'skill', 'metadata'):
        assert (home / integration.FILES[key]).read_bytes() == old[key]
    held = json.loads(next((home / '.codex').glob('pipeline-integration-backup-*/held.json')).read_text())
    assert held['concurrent_or_restore_conflicts'] == ['rules']
    assert set(held['restored']) == {'config', 'skill'}


@pytest.mark.parametrize('extra', ['[mcp_servers."cochem-pipeline".env]\nTOKEN="private"\n',
                                  '[mcp_servers."cochem-pipeline"]\ncommand="duplicate"\n'])
def test_unreviewed_nested_or_duplicate_server_settings_refuse(extra):
    with pytest.raises(ValueError):
        integration.patch_config(('[mcp_servers."cochem-pipeline"]\ncommand="old"\nargs=[]\n' + extra).encode(), 'root', 'client')
