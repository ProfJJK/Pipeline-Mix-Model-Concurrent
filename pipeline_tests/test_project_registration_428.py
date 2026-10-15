"""Registration authority and restart/idempotency checks without invoking Git."""
from dataclasses import replace

import pytest

from cochem_pipeline.coding import CodingProject
from cochem_pipeline.project_registration import ProjectRegistry, RegistrationPolicy


def make_registry(tmp_path, monkeypatch):
    sources = tmp_path / 'sources'
    sources.mkdir()
    repository = sources / 'example'
    repository.mkdir()
    registry = ProjectRegistry(tmp_path/'private', RegistrationPolicy((sources,)), git_executable='unused', static_projects={})
    calls = []
    def prepare(project, destination, context, **kwargs):
        if kwargs.get('inspect_only'):
            return {'source_commit':'a'*40,'working_snapshot_sha256':'b'*64}
        calls.append(project)
        private = destination/'prepared'
        private.mkdir(parents=True)
        return replace(project, repository=private, auto_integrate=True), {
            'source_repository':str(project.repository), 'prepared_repository':str(private),
            'source_branch':project.branch, 'captured_paths':['src','tests'],
            'changed_paths':['src/main.py'], 'source_commit':'a'*40,'working_snapshot_sha256':'b'*64}
    monkeypatch.setattr('cochem_pipeline.coding_git.prepare_isolated_project', prepare)
    raw = {'repository':str(repository),'branch':'main','allowed_paths':['src'],'test_paths':['tests']}
    return registry, raw, calls


def test_exact_registration_is_durable_and_idempotent(tmp_path, monkeypatch):
    registry, raw, calls = make_registry(tmp_path,monkeypatch)
    proof=registry.prepare('example',raw)
    restarted=ProjectRegistry(registry.root,registry.policy,git_executable='unused',static_projects={})
    assert restarted.prepare('example',raw)==proof
    assert len(calls)==1
    assert restarted.projects()['example'].repository != calls[0].repository
    assert proof['original_checkout_modified'] is False
    assert proof['source_integration']=='REVIEW_REQUIRED'
    with pytest.raises(ValueError,match='different source or scope'):
        restarted.prepare('example',dict(raw,allowed_paths=['lib']))


def test_delivery_requires_private_provenance_and_rechecks_original_scoped_snapshot(tmp_path, monkeypatch):
    registry, raw, _ = make_registry(tmp_path, monkeypatch)
    assert registry.delivery_provenance('missing') is None
    registry.static_projects['static'] = CodingProject.from_dict('static', dict(raw, auto_integrate=True))
    assert registry.delivery_provenance('static') is None
    registry.prepare('example', raw)
    provenance = registry.delivery_provenance('example')
    assert provenance['source_project']['repository'] == raw['repository']
    assert provenance['prepared_project']['repository'] != raw['repository']
    assert provenance['source_project']['auto_integrate'] is False
    assert registry.verify_delivery_source('example')['status'] == 'SOURCE_CAPTURE_MATCHES'
    observed = []
    def changed(project, destination, context, **kwargs):
        observed.append((project, context, kwargs))
        return {'source_commit':'a'*40, 'working_snapshot_sha256':'c'*64}
    monkeypatch.setattr('cochem_pipeline.coding_git.prepare_isolated_project', changed)
    with pytest.raises(ValueError, match='changed after preparation'):
        registry.verify_delivery_source('example')
    assert observed[0][0].repository == registry.policy.authorize(raw['repository'])
    assert observed[0][2]['inspect_only'] is True


@pytest.mark.parametrize('field,value', [('captured_paths', ['src']),
    ('prepared_repository', 'wrong-path'), ('original_checkout_modified', True)])
def test_delivery_provenance_refuses_changed_registration_authority(tmp_path, monkeypatch, field, value):
    import json
    import sqlite3
    registry, raw, _ = make_registry(tmp_path, monkeypatch)
    proof = registry.prepare('example', raw)
    proof[field] = value
    with sqlite3.connect(registry.db) as conn:
        conn.execute('UPDATE projects SET evidence=? WHERE project_id=?', (json.dumps(proof), 'example'))
    with pytest.raises(ValueError):
        registry.delivery_provenance('example')


@pytest.mark.parametrize('name',['Gdrive','Google Drive','OneDrive','Dropbox'])
def test_sync_roots_refused_even_if_configured(tmp_path,name):
    with pytest.raises(ValueError,match='synchronized'):
        RegistrationPolicy.from_dict({'source_roots':[str(tmp_path/name)]})


def test_out_of_scope_and_fixture_aliases_never_prepare(tmp_path,monkeypatch):
    registry, raw, calls=make_registry(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='outside'):
        registry.prepare('example',dict(raw,repository=str(tmp_path)))
    with pytest.raises(ValueError,match='acceptance fixture'):
        registry.prepare('windows-acceptance',raw)
    registry.static_projects['windows-acceptance']=CodingProject.from_dict('windows-acceptance',raw)
    with pytest.raises(ValueError,match='aliased'):
        registry.prepare('disguised',raw)
    assert calls==[]


def test_registration_cannot_supply_auto_integration_or_planning_authority(tmp_path,monkeypatch):
    registry,raw,calls=make_registry(tmp_path,monkeypatch)
    for field in ['auto_integrate','planning','runtime_version']:
        with pytest.raises(ValueError,match='accepts'):
            registry.prepare('example',dict(raw,**{field:True}))
    assert not calls


def test_preparation_preserves_scoped_dirty_new_and_deleted_bytes(tmp_path,monkeypatch):
    from cochem_pipeline import coding_git as git
    source=tmp_path/'source'
    (source/'src').mkdir(parents=True)
    (source/'src/main.py').write_bytes(b'new work\n')
    (source/'src/new.py').write_bytes(b'new file\n')
    (source/'unrelated.txt').write_bytes(b'other agent changes\n')
    original={'src/main.py':b'old\n','src/deleted.py':b'delete me\n','unrelated.txt':b'original\n'}
    snap=git.RepositorySnapshot(str(source),'main','refs/heads/main','a'*40,original,{}, {},'b'*64)
    monkeypatch.setattr(git,'_trusted_git_executable',lambda value:'unused')
    monkeypatch.setattr(git,'capture_repository',lambda *a,**kw:snap)
    monkeypatch.setattr(git,'_current_commit',lambda repository,ref:'a'*40 if repository==source else None)
    calls=[]
    def plumbing(repo,*args,**kw):
        if args[:2]==('rev-parse','--is-bare-repository'): return b'false\n'
        if args[:1]==('symbolic-ref',): return b'refs/heads/main\n'
        if args[:1]==('ls-files',): return b'src/new.py\0unrelated.txt\0'
        assert args[0]=='update-ref'
        return b''
    monkeypatch.setattr(git,'_git',plumbing)
    private=tmp_path/'private'
    def stage(self,baseline,files,**kw):
        calls.append(files)
        return {'staging_repository':str(private),'result_commit':'c'*40}
    monkeypatch.setattr(git.GitStager,'stage',stage)
    project=CodingProject('project',source,'main',('src',))
    prepared, proof=git.prepare_isolated_project(project,tmp_path/'staging',git_executable='unused')
    assert calls==[{'src/main.py':b'new work\n','src/new.py':b'new file\n','unrelated.txt':b'original\n'}]
    assert proof['changed_paths']==['src/deleted.py','src/main.py','src/new.py']
    assert prepared.repository==private
    assert prepared.branch=='prepared-input'
    assert (source/'unrelated.txt').read_bytes()==b'other agent changes\n'
