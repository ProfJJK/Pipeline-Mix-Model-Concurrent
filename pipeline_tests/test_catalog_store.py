"""Catalog adoption uses temporary SQLite; publication evidence is a fixture."""
import json

import pytest

from cochem_pipeline.catalog_journal import initialize, publish
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from pipeline_tests.test_catalog_journal import connection, change


def setup(tmp_path):
    path=tmp_path/'board.db'
    baseline=load_routing_policy({'policy_version':3})
    store=JobStore(path,routing_policy=baseline)
    store.submit('Existing note',['Keep old capture'],1,workflow_id='old')
    store.close()
    with connection(path) as conn:
        conn.execute('BEGIN IMMEDIATE');initialize(conn,baseline);conn.commit()
    return path,baseline


def capture(store, workflow):
    with store._connection() as conn:
        return json.loads(conn.execute('SELECT policy_json FROM pipeline_routing_workflows WHERE workflow_id=?',
            (workflow,)).fetchone()[0])


def test_new_submissions_adopt_published_generation_without_rewriting_captures(tmp_path):
    path,baseline=setup(tmp_path)
    store=JobStore(path,routing_policy=baseline,catalog_enabled=True)
    old=capture(store,'old')
    authority,proof=change(baseline,2)
    with store._write() as conn:
        assert conn.execute('PRAGMA synchronous').fetchone()[0]==2
        publish(conn,authority,proof)  # fixture only, no production activation API
    store.submit('New note',['New capture'],1,workflow_id='new')
    assert capture(store,'new')==authority.change.policy.as_dict()
    store.submit('Existing note',['Keep old capture'],1,workflow_id='old')
    assert capture(store,'old')==old
    store.close()
    reopened=JobStore(path,routing_policy=baseline,catalog_enabled=True)
    reopened.submit('After restart',['Durable generation'],1,workflow_id='restart')
    assert capture(reopened,'restart')==authority.change.policy.as_dict()
    reopened.close()


def test_catalog_mode_requires_explicit_prior_journal_initialization(tmp_path):
    with pytest.raises(ValueError,match='initialized'):
        JobStore(tmp_path/'new.db',routing_policy={'policy_version':3},catalog_enabled=True)


def test_disabled_catalog_mode_refuses_to_silently_ignore_persisted_authority(tmp_path):
    path,baseline=setup(tmp_path)
    with pytest.raises(ValueError,match='catalog-enabled'):
        JobStore(path,routing_policy=baseline)


def test_unrelated_installed_baseline_is_refused(tmp_path):
    path,baseline=setup(tmp_path)
    different,_=change(baseline,99)
    with pytest.raises(ValueError,match='baseline'):
        JobStore(path,routing_policy=different.change.policy,catalog_enabled=True)


def test_catalog_selection_occurs_inside_submission_transaction(tmp_path,monkeypatch):
    path,baseline=setup(tmp_path)
    store=JobStore(path,routing_policy=baseline,catalog_enabled=True)
    original=store._current_routing_policy
    observations=[]
    def observed(conn):
        observations.append(conn.in_transaction)
        return original(conn)
    monkeypatch.setattr(store,'_current_routing_policy',observed)
    store.submit('New note',['Test transaction'],1)
    store.submit_preflight('preflight')
    assert observations and all(observations)
    store.close()


def test_coding_submission_uses_new_authority_but_old_claim_keeps_its_capture(tmp_path):
    from cochem_pipeline.coding import CodingProject
    from cochem_pipeline.coding_git import RepositorySnapshot, snapshot_digest
    from cochem_pipeline.container_policy import DockerPolicy
    path,baseline=setup(tmp_path)
    store=JobStore(path,routing_policy=baseline,catalog_enabled=True)
    authority,proof=change(baseline,2)
    with store._write() as conn:publish(conn,authority,proof)
    repository=tmp_path/'fixture-repository';repository.mkdir()
    project=CodingProject.from_dict('fixture',{'repository':str(repository),'branch':'main',
        'allowed_paths':['src'],'test_paths':['tests']})
    files={'src/answer.py':b'ANSWER = 42\n'};modes={'src/answer.py':'100644'}
    snapshot=RepositorySnapshot(str(repository),'main','refs/heads/main','a'*40,files,modes,
        {'src/answer.py':'b'*40},snapshot_digest(files,modes))
    store.submit_coding_snapshot(project,'Review fixture answer',['REQ-1'],snapshot,DockerPolicy.from_dict({}),
        workflow_id='coding')
    assert capture(store,'coding')==authority.change.policy.as_dict()
    node=store.claim('fixture-owner',requires_cleanup=False,allowed_kinds=('MANIFEST_GENERATOR',))
    assert node['workflow_id']=='old'
    assert node['routing_policy']==baseline.as_dict()
    store.close()


def test_partial_catalog_schema_is_not_silently_completed(tmp_path):
    path,baseline=setup(tmp_path)
    with connection(path) as conn:conn.execute('DROP TABLE pipeline_catalog_active')
    with pytest.raises(ValueError,match='initialized'):
        JobStore(path,routing_policy=baseline,catalog_enabled=True)
    with connection(path) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='pipeline_catalog_active'").fetchone() is None
