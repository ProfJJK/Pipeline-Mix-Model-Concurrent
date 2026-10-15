"""Physical temporary snapshots and SQLite; inert native/reviewer ports only.

The graph registration below is a controller fixture; these tests verify the
join boundary, not independent approval or Windows/native acceptance.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from cochem_pipeline.content_review_428 import review_contract
from cochem_pipeline.fracture_runtime_428 import FractureRuntime
from cochem_pipeline.microtask_board_428 import MicrotaskBoardRuntime
from cochem_pipeline.task_routing import digest
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_task_content_verification_e2e_428 import content_task


@pytest.fixture(autouse=True)
def captured_fracture_inputs(monkeypatch):
    # Capture the controller's fracture authority before jobs are queued. The
    # ordinary board is only an inert execution harness for these scope tests.
    submit = MicrotaskBoardRuntime._submit_board_job_for_node
    def scoped(self, task_id, gen_sha, node, *args, **kwargs):
        node = deepcopy(node)
        node.update(attempt_lineage_id=node['microtask_id'], lineage_kind='FAILURE_FRACTURE',
            fracture_context=dict(fracture_id='fracture-fixture', graph_sha256='f'*64,
                dossier_sha256='d'*64, lineage_root='failed-root', failed_microtask_id='failed-original'))
        return submit(self, task_id, gen_sha, node, *args, **kwargs)
    monkeypatch.setattr(MicrotaskBoardRuntime, '_submit_board_job_for_node', scoped)


@pytest.fixture
def joined_scope(content_task):
    store, journal, artifacts, producer, args, outcomes = content_task
    board = MicrotaskBoardRuntime(journal, store, artifact_runtime=artifacts)
    snapshot = board.board_status('content-task')
    children = snapshot['nodes']
    assembly = next(n for n in children if n['role'] == 'assembly')
    final = next(n for n in children if n['role'] == 'final_test')
    failed = deepcopy(assembly)
    failed.update(microtask_id='failed-original', attempt_lineage_id='failed-root',
                  plan_generation_sha256=args['generation'], release_criteria=final['release_criteria'])
    fracture = FractureRuntime(outcomes.accounting.ledger, producer['payload']['task_catalog'])
    artifacts.runtime.task_planning = SimpleNamespace(fracture_runtime=fracture, journal=journal,
                                                     attempt_runtime=outcomes.accounting)
    record = dict(fracture_id='fracture-fixture', lineage_root='failed-root', failed_scope_id='failed-original',
                  graph_sha256='f'*64)
    fracture.ledger.create('failed-root', complexity=5)
    with fracture.ledger._write() as conn:
        conn.execute('INSERT INTO task428_fractures VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (record['fracture_id'], 'failed-root', 'failed-original', 10, 'dossier', 'd' * 64,
             record['graph_sha256'], 5, 'fixture-family', json.dumps({'children': children}), 1))
        for child in children:
            job = store.get(child['job_id'])
            spec = job['payload']['microtask_node']
            profile_id = child['output']['profile_id']
            model = job['payload']['task_catalog']['models'][profile_id]
            fields = dict(child_id=child['microtask_id'], fracture_id=record['fracture_id'],
                lineage_root='failed-root', failed_scope_id='failed-original', dossier_id='dossier',
                dossier_sha256='d'*64, graph_sha256=record['graph_sha256'], role=spec['role'],
                complexity=spec['complexity'], selected_profile_id=profile_id,
                selected_model_family=model['family'], selected_effort=model['effort'],
                escalated_scope=0, needs_owner_approval=0, owner_approval_json=None,
                status='COMPLETED', artifact_sha256=child['artifact_sha256'], node_json=json.dumps(spec), updated_at=1)
            fields.update({key+'_json': json.dumps(spec[key]) for key in
                ('task_types','requirement_ids','deliverables','release_criteria','depends_on')})
            conn.execute('INSERT INTO task428_fracture_nodes ('+','.join(fields)+') VALUES ('+
                         ','.join('?' for _ in fields)+')', tuple(fields.values()))
    return artifacts, failed, record, children, producer


def accept_review(store):
    reviewer = store.claim('inert-reviewer', worker_slot='slot3', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert reviewer['payload']['planning_intent']['stage'] == 'CONTENT_REVIEW'
    output = review_contract(reviewer['payload'])
    output.update(accepted=True, findings=[])
    path, text = next(iter(reviewer['payload']['content_review']['artifacts'].items()))
    for item in output['requirements']:
        item.update(satisfied=True, artifact_path=path, excerpt=text, assessment='Observed bound content')
    for item in output['criteria']:
        item.update(satisfied=True, assessment='Observed bound content')
    store.clear_execution_quarantine(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'])
    store.complete(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'], output,
                   accepted_receipt(reviewer, output))


def test_join_waits_for_review_then_resolves_exact_snapshot_without_rewriting_producer(joined_scope):
    artifacts, failed, record, children, producer = joined_scope
    before = deepcopy(artifacts.store.get(producer['job_id']))
    assert artifacts.fracture_join('content-task', failed, record, children)['status'] == 'WAITING_FOR_INDEPENDENT_CONTENT_REVIEW'
    accept_review(artifacts.store)
    joined = artifacts.fracture_join('content-task', failed, record, children)
    assert joined['status'] == 'COMPLETED' and joined['job_id'] == producer['job_id']
    final = next(row for row in children if row['role'] == 'final_test')
    assert joined['output']['predecessor_artifact_hashes'] == {final['microtask_id']: final['artifact_sha256']}
    intent = dict(task_id='content-task', plan_generation_sha256=failed['plan_generation_sha256'])
    winner = artifacts._accepted_dependency(intent, failed['microtask_id'], joined['output'])
    assert winner['job_id'] == producer['job_id']
    assert artifacts.store.get(producer['job_id']) == before
    assert artifacts.fracture_join('content-task', failed, record, children) == joined
    changed = deepcopy(joined['output']); changed['artifact_text'] += ' forged'
    with pytest.raises(ValueError, match='alias'):
        artifacts._accepted_dependency(intent, failed['microtask_id'], changed)
    with pytest.raises(ValueError, match='alias'):
        artifacts._accepted_dependency(intent, 'unrelated-scope', joined['output'])


def test_join_refuses_missing_child_wrong_graph_or_fence(joined_scope):
    artifacts, failed, record, children, _ = joined_scope
    with pytest.raises(ValueError, match='complete bounded'):
        artifacts.fracture_join('content-task', failed, record, children[1:])
    with pytest.raises(ValueError, match='durable graph'):
        artifacts.fracture_join('content-task', failed, dict(record, graph_sha256='0'*64), children)
    changed = deepcopy(children); changed[0]['output']['producer_fencing_token'] += 1
    with pytest.raises(ValueError, match='winning producer'):
        artifacts.fracture_join('content-task', failed, record, changed)


@pytest.mark.parametrize('changed', ['depends_on', 'attempt_lineage_id', 'fracture_context', 'failed_scope'])
def test_join_rebinds_compiled_child_authority_and_failed_scope(joined_scope, monkeypatch, changed):
    artifacts, failed, record, children, _ = joined_scope
    if changed == 'failed_scope':
        failed = dict(failed, microtask_id='unrelated-original')
    else:
        original_get = artifacts.store.get
        target = children[0]['job_id']
        def changed_get(job_id):
            job = original_get(job_id)
            if job_id == target:
                spec = job['payload']['microtask_node']
                if changed == 'depends_on':
                    spec['depends_on'] = ['unregistered-dependency']
                elif changed == 'attempt_lineage_id':
                    spec['attempt_lineage_id'] = 'unrelated-lineage'
                else:
                    spec['fracture_context'] = dict(spec['fracture_context'], dossier_sha256='0'*64)
            return job
        monkeypatch.setattr(artifacts.store, 'get', changed_get)
    with pytest.raises(ValueError, match='compiled|failed scope'):
        artifacts.fracture_join('content-task', failed, record, children)
