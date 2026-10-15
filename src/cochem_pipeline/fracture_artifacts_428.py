"""Join a fractured scope only through its exact cleaned, verified producers.

The alias is controller metadata, never a synthetic native completion. It lets
unchanged downstream nodes retain their original dependency name while reading
the concrete tested final snapshot and its immutable provenance.
"""
from copy import deepcopy
import json

from .task_routing import digest
from .workflow_428 import _id


def initialize(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS task428_fracture_artifact_joins(
            join_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, microtask_id TEXT NOT NULL,
            generation TEXT NOT NULL, binding_json TEXT NOT NULL, output_json TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS fracture428_join_no_update BEFORE UPDATE ON task428_fracture_artifact_joins
        BEGIN SELECT RAISE(ABORT,'fracture artifact join is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS fracture428_join_no_delete BEFORE DELETE ON task428_fracture_artifact_joins
        BEGIN SELECT RAISE(ABORT,'fracture artifact join is immutable'); END;
    ''')


def _winner(artifacts, row, task_id, generation):
    job = artifacts.store.get(row['job_id'])
    node, intent = job['payload']['microtask_node'], job['payload']['planning_intent']
    if (intent['task_id'] != task_id or intent['plan_generation_sha256'] != generation
            or node['microtask_id'] != row['microtask_id'] or row['status'] != 'COMPLETED'):
        raise ValueError('Fracture child belongs to another task, generation or scope')
    from .microtask_board_428 import validate_microtask_execution_output
    output = validate_microtask_execution_output(node, job['output'])
    projected = row.get('output') or {}
    if (any(output[key] != projected.get(key) for key in output)
            or row.get('artifact_sha256') != output['artifact_sha256']
            or any(projected.get('producer_' + key) != job[key]
                   for key in ('job_id', 'attempt_id', 'fencing_token'))):
        raise ValueError('Fracture child projection differs from the winning producer')
    snapshot = artifacts.accepted_snapshot(job)
    return job, output, snapshot


def join(artifacts, task_id, failed_node, fracture_record, completed_children):
    """Called by the controller board adapter, never by native/public input."""
    task_id = _id(task_id)
    planner = artifacts.runtime.task_planning
    ledger = planner.fracture_runtime.ledger
    fracture_id = _id(fracture_record['fracture_id'])
    with ledger._write() as conn:
        record = conn.execute('SELECT * FROM task428_fractures WHERE fracture_id=?', (fracture_id,)).fetchone()
        if record is None:
            raise ValueError('Fracture has no committed controller graph')
        graph = json.loads(record['graph_json'])
        if any(fracture_record.get(key) != record[key] for key in
               ('lineage_root', 'failed_scope_id', 'graph_sha256')):
            raise ValueError('Fracture record differs from durable graph')
        node_records = {r['child_id']: dict(r) for r in conn.execute(
            'SELECT * FROM task428_fracture_nodes WHERE fracture_id=?', (fracture_id,))}
        member = conn.execute('SELECT root FROM task428_members WHERE task_id=?',
                              (failed_node['attempt_lineage_id'],)).fetchone()
    if (failed_node['microtask_id'] != record['failed_scope_id']
            or member is None or member[0] != record['lineage_root']):
        raise ValueError('Fracture does not replace this failed scope and captured lineage')
    with planner.journal._write() as conn:
        task = planner.journal._read(conn, task_id)
        state = json.loads(task['state_json'])
    generation = failed_node['plan_generation_sha256']
    children = {row['microtask_id']: row for row in completed_children}
    if (len(children) != len(completed_children) or set(children) != set(node_records)
            or len(children) > 64):
        raise ValueError('Fracture join requires its complete bounded child graph')
    if any(row['status'] != 'COMPLETED' for row in children.values()):
        return dict(status='WAITING_FOR_FRACTURE_CHILDREN')
    winners = {}
    for child_id, row in children.items():
        registration = node_records[child_id]
        if registration['needs_owner_approval'] and not registration['owner_approval_json']:
            return dict(status='HOLD_OWNER_APPROVAL', blocking_microtask_id=child_id)
        job, output, snapshot = _winner(artifacts, row, task_id, generation)
        spec = job['payload']['microtask_node']
        for key in ('role', 'complexity'):
            if spec[key] != registration[key]:
                raise ValueError('Fracture child classification differs from compiled scope')
        from .planning_gateway import validate_stage_output
        if validate_stage_output(job['payload'], job['output'], job['route']) != registration['selected_profile_id']:
            raise ValueError('Fracture child executed a different compiled model profile')
        expected_context = dict(fracture_id=fracture_id, graph_sha256=record['graph_sha256'],
            dossier_sha256=record['dossier_sha256'], lineage_root=record['lineage_root'],
            failed_microtask_id=record['failed_scope_id'])
        if (spec.get('attempt_lineage_id') != child_id
                or spec.get('lineage_kind') != 'FAILURE_FRACTURE'
                or spec.get('fracture_context') != expected_context):
            raise ValueError('Fracture child identity differs from its compiled authority')
        for key in ('task_types', 'requirement_ids', 'deliverables', 'release_criteria', 'depends_on'):
            if spec[key] != json.loads(registration[key + '_json']):
                raise ValueError('Fracture child contract differs from compiled graph')
        winners[child_id] = (job, output, snapshot)
    assemblies = [cid for cid, row in children.items() if row['role'] == 'assembly']
    finals = [cid for cid, row in children.items() if row['role'] == 'final_test']
    if len(assemblies) != 1 or len(finals) != 1:
        raise ValueError('Fracture join needs one terminal assembly and final-test producer')
    assembly_id, final_id = assemblies[0], finals[0]
    terminal, _, accepted = winners[final_id]
    ancestors = artifacts._dependency_ancestors(terminal, cache={})
    if any(job['job_id'] not in ancestors for cid, (job, _, _) in winners.items() if cid != final_id):
        raise ValueError('Fracture final snapshot does not descend from every child')
    node = terminal['payload']['microtask_node']
    if (set(node['requirement_ids']) != set(failed_node['requirement_ids'])
            or not set(failed_node['release_criteria']) <= set(node['release_criteria'])):
        raise ValueError('Fracture terminal contract does not cover the failed scope')
    physical = artifacts.ensure_verification(terminal, node['requirement_ids'])
    if physical['status'] != 'VERIFIED':
        return physical
    if physical['output']['verification_kind'] == 'artifact_integrity':
        from .content_review_428 import ContentReviewRuntime
        reviewer = ContentReviewRuntime(planner.journal, artifacts.store,
                                        attempt_accounting=planner.attempt_runtime)
        reviewed = reviewer.ensure(task_id, state=state, generation=generation,
            producers=[winners[assembly_id][0]['job_id'], terminal['job_id']], physical=physical,
            scope_producer_id=terminal['job_id'])
        if reviewed['status'] != 'VERIFIED':
            return reviewed
    proof = artifacts.verification_outcome(terminal)
    if proof['status'] != 'VERIFIED':
        return proof
    # Project only original requirements/criteria; the exact concrete producer
    # remains bound in metadata. No native output or failed job is rewritten.
    from .microtask_board_428 import validate_microtask_execution_output
    assembly, _, assembly_snapshot = winners[assembly_id]
    projected = deepcopy(assembly['output'])
    terminal_files = artifacts.store.coding_files(accepted['snapshot_sha256'])
    assembly_files = artifacts.store.coding_files(assembly_snapshot['snapshot_sha256'])
    for item in projected['deliverables']:
        data = item['content'].encode('utf-8')
        if terminal_files.get(item['name']) != data or assembly_files.get(item['name']) != data:
            raise ValueError('Fracture assembly deliverable differs from the physically verified final bytes')
    projected['requirement_evidence'] = [x for x in projected['requirement_evidence']
                                       if x['requirement_id'] in failed_node['requirement_ids']]
    projected['release_criteria_results'] = [deepcopy(x) for x in terminal['output']['release_criteria_results']
                                           if x['criterion'] in failed_node['release_criteria']]
    output = validate_microtask_execution_output(failed_node, projected)
    binding = dict(schema='cochem-fracture-artifact-join/4.2.8', task_id=task_id,
        generation=generation, failed_node=deepcopy(failed_node), fracture_id=fracture_id,
        graph_sha256=record['graph_sha256'], graph_capture_sha256=digest(graph), physical_proof=proof,
        source_snapshot_sha256=accepted['snapshot_sha256'], producer_job_id=terminal['job_id'],
        producer_attempt_id=terminal['attempt_id'], producer_fencing_token=terminal['fencing_token'],
        producer_output_sha256=digest(terminal['output']), child_producers={cid: dict(job_id=job['job_id'],
            attempt_id=job['attempt_id'], fencing_token=job['fencing_token'], output_sha256=digest(job['output']))
            for cid, (job, _, _) in winners.items()})
    join_id = 'fracture-join428-' + digest(binding)[:40]
    output.update(fracture_join_id=join_id,
        predecessor_artifact_hashes={final_id: children[final_id]['artifact_sha256']},
        producer_job_id=terminal['job_id'],
        producer_attempt_id=terminal['attempt_id'], producer_fencing_token=terminal['fencing_token'])
    raw, result = json.dumps(binding, sort_keys=True), json.dumps(output, sort_keys=True)
    with artifacts.store._write() as conn:
        if conn.execute('SELECT 1 FROM task428_cancelled_tasks WHERE task_id=?', (task_id,)).fetchone():
            return dict(status='TASK_VERIFICATION_CANCELLED')
        old = conn.execute('SELECT binding_json,output_json FROM task428_fracture_artifact_joins WHERE join_id=?',
                           (join_id,)).fetchone()
        if old is not None and tuple(old) != (raw, result):
            raise ValueError('Fracture join changed after capture')
        conn.execute('INSERT OR IGNORE INTO task428_fracture_artifact_joins VALUES(?,?,?,?,?,?)',
                     (join_id, task_id, failed_node['microtask_id'], generation, raw, result))
    return dict(status='COMPLETED', output=output, artifact_sha256=output['artifact_sha256'],
                job_id=terminal['job_id'], fracture_join_id=join_id)


def resolve(artifacts, intent, dependency_id, output):
    with artifacts.store._connection() as conn:
        row = conn.execute('SELECT * FROM task428_fracture_artifact_joins WHERE join_id=?',
                           (_id(output['fracture_join_id']),)).fetchone()
    if (row is None or row['task_id'] != intent['task_id'] or row['microtask_id'] != dependency_id
            or row['generation'] != intent['plan_generation_sha256']
            or json.loads(row['output_json']) != output):
        raise ValueError('Fracture alias does not bind this dependency')
    binding = json.loads(row['binding_json'])
    if row['join_id'] != 'fracture-join428-' + digest(binding)[:40]:
        raise ValueError('Fracture alias commitment differs')
    job = artifacts.store.get(binding['producer_job_id'])
    if (any(job[key] != binding['producer_' + key] for key in ('attempt_id', 'fencing_token'))
            or digest(job['output']) != binding['producer_output_sha256']
            or artifacts.accepted_snapshot(job)['snapshot_sha256'] != binding['source_snapshot_sha256']
            or artifacts.verification_outcome(job) != binding['physical_proof']):
        raise ValueError('Fracture alias producer or verification changed')
    return job
