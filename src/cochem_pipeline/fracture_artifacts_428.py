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
    if (row.get('output') or {}).get('fracture_join_id'):
        job = resolve(artifacts, dict(task_id=task_id, plan_generation_sha256=generation),
                      row['microtask_id'], row['output'])
        binding = _alias_binding(artifacts, row['output']['fracture_join_id'])
        if row['status'] != 'COMPLETED' or row['job_id'] != job['job_id']:
            raise ValueError('Nested fracture differs from its winning producer')
        from .microtask_board_428 import validate_microtask_execution_output
        output = validate_microtask_execution_output(binding['failed_node'],
            {key: row['output'][key] for key in ('artifact_text', 'deliverables',
                'requirement_evidence', 'release_criteria_results')})
        if row['artifact_sha256'] != output['artifact_sha256']:
            raise ValueError('Nested fracture projection differs from its winning producer')
        return job, output, artifacts.accepted_snapshot(job)
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
    from .planning_fractures_428 import validated_fracture_source
    source = validated_fracture_source(planner, task_id, fracture_record)
    source_payload = source['payload']
    expected_scope = dict(source_payload['microtask_node'],
        plan_generation_sha256=source_payload['planning_intent']['plan_generation_sha256'])
    if failed_node != expected_scope:
        raise ValueError('Fracture failed scope differs from its immutable original source contract')
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
        nested = row.get('output', {}).get('fracture_join_id')
        spec = (_alias_binding(artifacts, nested)['failed_node'] if nested
                else job['payload']['microtask_node'])
        from .fracture_routes_428 import effective_registration
        with ledger._write() as conn:
            registration = effective_registration(conn, registration,
                amendment_id=spec.get('fracture_route_amendment'))
        if spec.get('fracture_route_context') != registration.get('fracture_route_context'):
            raise ValueError('Fracture child reviewed context differs from its exact route')
        if registration.get('route_catalog_sha256') and digest(job['payload']['task_catalog']) != registration['route_catalog_sha256']:
            raise ValueError('Fracture child catalog differs from its reviewed route')
        if row['role'] != registration['role']:
            raise ValueError('Fracture child role differs from compiled scope')
        for key in ('role', 'complexity'):
            if spec[key] != registration[key]:
                raise ValueError('Fracture child classification differs from compiled scope')
        from .planning_gateway import validate_stage_output
        if nested:
            # The failed outer intended profile remains provenance, not a claim
            # that it completed. Concrete execution belongs to the inner proof.
            selected = spec.get('selected_profile_id', spec.get('routed_profile_id'))
        else:
            selected = validate_stage_output(job['payload'], job['output'], job['route'])
        if selected != registration['selected_profile_id']:
            raise ValueError('Fracture child differs from its compiled model authority')
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
        original_final = any(n['id'] == failed_node['microtask_id'] and n['role'] == 'final_test'
                             for n in state['microtasks'])
        reviewed = reviewer.ensure(task_id, state=state, generation=generation,
            producers=[winners[assembly_id][0]['job_id'], terminal['job_id']], physical=physical,
            scope_producer_id=None if original_final else terminal['job_id'])
        if reviewed['status'] != 'VERIFIED':
            return reviewed
    review_binding = (reviewed['evidence']['binding_sha256']
                      if physical['output']['verification_kind'] == 'artifact_integrity' else None)
    proof = artifacts.verification_outcome(terminal, content_binding_sha256=review_binding)
    if proof['status'] != 'VERIFIED':
        return proof
    # Project only original requirements/criteria; the exact concrete producer
    # remains bound in metadata. No native output or failed job is rewritten.
    from .microtask_board_428 import validate_microtask_execution_output
    assembly, _, assembly_snapshot = winners[assembly_id]
    projected_source = terminal['output'] if failed_node['role'] == 'final_test' else winners[assembly_id][1]
    projected = {key: deepcopy(projected_source[key]) for key in
                 ('artifact_text', 'deliverables', 'requirement_evidence', 'release_criteria_results')}
    terminal_files = artifacts.store.coding_files(accepted['snapshot_sha256'])
    assembly_files = artifacts.store.coding_files(assembly_snapshot['snapshot_sha256'])
    for item in projected['deliverables']:
        data = item['content'].encode('utf-8')
        if (terminal_files.get(item['name']) != data
                or (failed_node['role'] != 'final_test' and assembly_files.get(item['name']) != data)):
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
            for cid, (job, _, _) in winners.items()},
        child_aliases={cid: deepcopy(row['output']) for cid, row in children.items()
                       if row.get('output', {}).get('fracture_join_id')})
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


def _alias_binding(artifacts, join_id):
    with artifacts.store._connection() as conn:
        row = conn.execute('SELECT binding_json FROM task428_fracture_artifact_joins WHERE join_id=?',
                           (_id(join_id),)).fetchone()
    if row is None:
        raise ValueError('Fracture alias has no immutable controller binding')
    return json.loads(row[0])


def resolve(artifacts, intent, dependency_id, output, *, _seen=None):
    seen = set(_seen or ())
    join_id = _id(output['fracture_join_id'])
    if join_id in seen or len(seen) >= 3:
        raise ValueError('Fracture alias ancestry exceeds the bounded failure windows')
    seen.add(join_id)
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
    for child_id, alias in binding.get('child_aliases', {}).items():
        prior = resolve(artifacts, intent, child_id, alias, _seen=seen)
        captured = binding['child_producers'][child_id]
        if (any(prior[key] != captured[key] for key in ('job_id', 'attempt_id', 'fencing_token'))
                or digest(prior['output']) != captured['output_sha256']):
            raise ValueError('Nested fracture alias producer changed')
    job = artifacts.store.get(binding['producer_job_id'])
    review_binding = (binding['physical_proof'].get('content_review') or {}).get('binding_sha256')
    if (any(job[key] != binding['producer_' + key] for key in ('attempt_id', 'fencing_token'))
            or digest(job['output']) != binding['producer_output_sha256']
            or artifacts.accepted_snapshot(job)['snapshot_sha256'] != binding['source_snapshot_sha256']
            or artifacts.verification_outcome(job, content_binding_sha256=review_binding) != binding['physical_proof']):
        raise ValueError('Fracture alias producer or verification changed')
    return job
