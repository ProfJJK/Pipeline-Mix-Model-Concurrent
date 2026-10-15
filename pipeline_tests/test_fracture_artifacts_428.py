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
        node.setdefault('attempt_lineage_id', node['microtask_id'])
        node['attempt_lineage_id'] = node['microtask_id']
        node['lineage_kind'] = 'FAILURE_FRACTURE'
        node.setdefault('fracture_context', dict(fracture_id='fracture-fixture', graph_sha256='f'*64,
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


def test_scoped_success_does_not_replace_whole_srs_review_or_rewrite_alias(joined_scope):
    from cochem_pipeline.content_review_428 import ContentReviewRuntime
    artifacts, failed, record, children, producer = joined_scope
    artifacts.fracture_join('content-task', failed, record, children)
    accept_review(artifacts.store)
    joined = artifacts.fracture_join('content-task', failed, record, children)
    planner = artifacts.runtime.task_planning
    with planner.journal._write() as conn:
        state = json.loads(planner.journal._read(conn, 'content-task')['state_json'])
    args = dict(state=state, generation=failed['plan_generation_sha256'],
        producers=[n['job_id'] for n in children if n['role'] in ('assembly', 'final_test')],
        physical=artifacts.ensure_verification(producer, producer['payload']['microtask_node']['requirement_ids']))
    review = ContentReviewRuntime(planner.journal, artifacts.store)
    waiting = review.ensure('content-task', **args)
    assert waiting['status'] == 'WAITING_FOR_INDEPENDENT_CONTENT_REVIEW'
    reviewer = artifacts.store.claim('inert-reviewer', worker_slot='slot3', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    output = review_contract(reviewer['payload'])
    artifacts.store.clear_execution_quarantine(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'])
    artifacts.store.complete(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'], output,
                             accepted_receipt(reviewer, output))
    assert review.ensure('content-task', **args)['status'] == 'CONTENT_REVIEW_REJECTED'
    assert review.committed_result(artifacts.store, producer['job_id'])['accepted'] is False
    # The inner scoped alias remains bound to its earlier positive judgment;
    # parent release still requires the separate, now rejected whole-SRS scope.
    intent = dict(task_id='content-task', plan_generation_sha256=failed['plan_generation_sha256'])
    assert artifacts._accepted_dependency(intent, failed['microtask_id'], joined['output'])['job_id'] == producer['job_id']
    with artifacts.store._connection() as conn:
        assert conn.execute('SELECT count(*) FROM task428_content_review_scopes').fetchone()[0] == 2


def test_failed_final_alias_projects_test_deliverables_not_assembly(joined_scope):
    artifacts, failed, record, children, producer = joined_scope
    node = producer['payload']['microtask_node']
    failed.update(role='final_test', deliverables=node['deliverables'], requirement_ids=node['requirement_ids'])
    artifacts.fracture_join('content-task', failed, record, children)
    accept_review(artifacts.store)
    joined = artifacts.fracture_join('content-task', failed, record, children)
    assert joined['status'] == 'COMPLETED'
    assert joined['output']['deliverables'] == producer['output']['deliverables']


def test_nested_alias_consumes_inner_verified_bytes_without_claiming_outer_model_success(joined_scope):
    import threading
    from cochem_pipeline.fracture_artifacts_428 import _alias_binding
    from cochem_pipeline.microtask_board_428 import validate_microtask_execution_output
    artifacts, failed, record, children, producer = joined_scope
    store, planner = artifacts.store, artifacts.runtime.task_planning
    outer_id, outer_sha = 'outer-fracture', 'e'*64
    outer_context = dict(fracture_id=outer_id, graph_sha256=outer_sha, dossier_sha256='b'*64,
                         lineage_root='failed-root', failed_microtask_id='outer-original')
    profile = next(n['output']['profile_id'] for n in children if n['role'] == 'assembly')
    failed.update(attempt_lineage_id='failed-original', lineage_kind='FAILURE_FRACTURE',
                  fracture_context=outer_context, routed_profile_id=profile)
    with planner.fracture_runtime.ledger._write() as conn:
        conn.execute('INSERT INTO task428_members VALUES(?,?)', ('failed-original', 'failed-root'))
    artifacts.fracture_join('content-task', failed, record, children)
    accept_review(store)
    inner = artifacts.fracture_join('content-task', failed, record, children)
    with planner.journal._write() as conn:
        row = planner.journal._read(conn, 'content-task')
        state, catalog = json.loads(row['state_json']), json.loads(row['catalog_json'])
        limit = row['flash_context_limit']
    spec = deepcopy(producer['payload']['microtask_node'])
    spec.update(microtask_id='outer-final', attempt_lineage_id='outer-final', depends_on=['failed-original'],
                deliverables=['outer-proof.md'], fracture_context=outer_context)
    board = MicrotaskBoardRuntime(planner.journal, store, artifact_runtime=artifacts)
    queued = board._submit_board_job_for_node('content-task', failed['plan_generation_sha256'], spec,
        state, catalog, limit, producer['payload']['planning_intent']['candidate_profiles'], {'failed-original': inner['output']})
    claimed = store.claim('inert-final', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert claimed['job_id'] == queued['job_id']
    output, receipt = artifacts.run(claimed, 'slot1', '', lambda: True, lambda _: None, threading.Event(),
                                    on_native_start=lambda _: None, on_native_end=lambda: None)
    store.clear_execution_quarantine(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'])
    store.complete(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'], output, receipt)
    final = store.get(claimed['job_id'])
    projected = validate_microtask_execution_output(spec, output)
    projected.update(producer_job_id=final['job_id'], producer_attempt_id=final['attempt_id'],
                     producer_fencing_token=final['fencing_token'])
    outer_children = [dict(microtask_id='failed-original', role='assembly', status='COMPLETED', **{
        key: inner[key] for key in ('job_id','output','artifact_sha256')}),
        dict(microtask_id='outer-final', role='final_test', status='COMPLETED', job_id=final['job_id'],
             output=projected, artifact_sha256=projected['artifact_sha256'])]
    outer_failed = dict(failed, microtask_id='outer-original', attempt_lineage_id='failed-root')
    outer_record = dict(fracture_id=outer_id, lineage_root='failed-root', failed_scope_id='outer-original', graph_sha256=outer_sha)
    with planner.fracture_runtime.ledger._write() as conn:
        conn.execute('INSERT INTO task428_fractures VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (outer_id, 'failed-root', 'outer-original', 20, 'outer-dossier', 'b'*64,
             outer_sha, 5, 'fixture-family', json.dumps({'children': outer_children}), 1))
        template = dict(conn.execute('SELECT * FROM task428_fracture_nodes LIMIT 1').fetchone())
        for row, child_spec, selected in [(outer_children[0], failed, profile),
                (outer_children[1], final['payload']['microtask_node'], producer['payload']['planning_intent']['candidate_profiles'][0])]:
            fields = dict(template, child_id=row['microtask_id'], fracture_id=outer_id, failed_scope_id='outer-original',
                dossier_sha256='b'*64, graph_sha256=outer_sha, role=child_spec['role'], complexity=child_spec['complexity'],
                selected_profile_id=selected, artifact_sha256=row['artifact_sha256'], node_json=json.dumps(child_spec))
            fields.update({key+'_json': json.dumps(child_spec[key]) for key in
                ('task_types','requirement_ids','deliverables','release_criteria','depends_on')})
            conn.execute('INSERT INTO task428_fracture_nodes ('+','.join(fields)+') VALUES ('+
                         ','.join('?' for _ in fields)+')', tuple(fields.values()))
    pending = artifacts.fracture_join('content-task', outer_failed, outer_record, outer_children)
    assert pending['status'] == 'WAITING_FOR_PHYSICAL_VERIFICATION'
    verifier = store.claim('inert-integrity', worker_slot='slot2', allowed_kinds=['TASK_VERIFY'], requires_cleanup=True)
    output, receipt, evidence = artifacts.run_verification(verifier, 'slot2', lambda: True, threading.Event())
    store.clear_execution_quarantine(verifier['job_id'], verifier['attempt_id'], verifier['fencing_token'])
    store.complete_task_verification(verifier['job_id'], verifier['attempt_id'], verifier['fencing_token'], output, receipt, evidence=evidence)
    assert artifacts.fracture_join('content-task', outer_failed, outer_record, outer_children)['status'] == 'WAITING_FOR_INDEPENDENT_CONTENT_REVIEW'
    accept_review(store)
    outer = artifacts.fracture_join('content-task', outer_failed, outer_record, outer_children)
    binding = _alias_binding(artifacts, outer['fracture_join_id'])
    assert binding['child_aliases']['failed-original'] == inner['output']
    assert binding['producer_job_id'] == final['job_id']
    intent = dict(task_id='content-task', plan_generation_sha256=failed['plan_generation_sha256'])
    assert artifacts._accepted_dependency(intent, 'outer-original', outer['output'])['job_id'] == final['job_id']
