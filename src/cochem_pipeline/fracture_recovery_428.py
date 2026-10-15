"""Reopen registered child projections only for accounted physical failures."""
import json

from .task_routing import digest


def reopen_physical_children(board, nodes, contexts):
    runtime = board.fracture_runtime
    if runtime is None:
        return
    affected = [node for node in nodes if node.get('fracture_context') and not node.get('fracture_join')
                and node['microtask_id'] in contexts]
    if not affected:
        return
    packet = dict(children=sorted(node['microtask_id'] for node in affected),
                  contexts={node['microtask_id']: contexts[node['microtask_id']] for node in affected})
    key, raw = digest(packet), json.dumps(packet, sort_keys=True)
    with runtime.ledger._write() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS task428_fracture_recoveries(
            recovery_id TEXT PRIMARY KEY, packet_json TEXT NOT NULL, previous_json TEXT NOT NULL)''')
        prior = conn.execute('SELECT packet_json FROM task428_fracture_recoveries WHERE recovery_id=?', (key,)).fetchone()
        if prior:
            if prior[0] != raw:
                raise ValueError('Fracture physical recovery commitment changed')
            return
        previous = []
        for node in affected:
            context = node['fracture_context']
            state = runtime.ledger._read(conn, node['attempt_lineage_id'])
            if state['root'] != context['lineage_root'] or state['stage'] != 'READY':
                raise ValueError('Fracture physical retry must preserve its ready shared lineage')
            row = conn.execute('SELECT * FROM task428_fracture_nodes WHERE child_id=?', (node['microtask_id'],)).fetchone()
            if row is None or row['fracture_id'] != context['fracture_id'] or row['status'] == 'FRACTURED_OBSOLETE':
                raise ValueError('Physical retry belongs to a stale fracture scope')
            for feedback in contexts[node['microtask_id']]['failed_checks']:
                producer = board.store.get(feedback['producer_job_id'])
                account = conn.execute("SELECT lineage_root FROM attempt428_outbox WHERE job_id=? AND attempt_id=? "
                    "AND fencing_token=? AND status='RECONCILED' AND staged_outcome='quality_failure'",
                    (producer['job_id'], producer['attempt_id'], producer['fencing_token'])).fetchone()
                if account is None or account[0] != state['root']:
                    raise ValueError('Fracture physical retry lacks its accounted producer fence')
            previous.append(dict(row))
        changed = set(packet['children'])
        for node in affected:
            row = next(item for item in previous if item['child_id'] == node['microtask_id'])
            dependencies = json.loads(row['depends_on_json'])
            ready = all(dep not in changed and conn.execute(
                "SELECT 1 FROM task428_fracture_nodes WHERE child_id=? AND status='COMPLETED'", (dep,)).fetchone()
                for dep in dependencies)
            status = 'HOLD_OWNER_APPROVAL' if row['needs_owner_approval'] else ('READY' if ready else 'BLOCKED_DAG')
            conn.execute('UPDATE task428_fracture_nodes SET status=?,artifact_sha256=NULL,updated_at=? WHERE child_id=?',
                         (status, float(runtime.clock()), node['microtask_id']))
        conn.execute('INSERT INTO task428_fracture_recoveries VALUES(?,?,?)',
                     (key, raw, json.dumps(previous, sort_keys=True)))


def complete_nested_alias(board, task_id, generation, node, output):
    """Advance an obsolete registered member from an immutable physical alias."""
    if not node.get('fracture_context'):
        return
    runtime = board.fracture_runtime
    child_id, join_id = node['microtask_id'], output['fracture_join_id']
    with board.store._connection() as conn:
        row = conn.execute('SELECT task_id,microtask_id,generation,binding_json,output_json FROM task428_fracture_artifact_joins '
                           'WHERE join_id=?', (join_id,)).fetchone()
    if (row is None or row['microtask_id'] != child_id or row['task_id'] != task_id
            or row['generation'] != generation or json.loads(row['output_json']) != output):
        raise ValueError('Nested fracture completion requires its exact persisted physical alias')
    binding = json.loads(row['binding_json'])
    if join_id != 'fracture-join428-' + digest(binding)[:40]:
        raise ValueError('Nested fracture alias commitment differs')
    if (binding['failed_node'] != node['fracture_join']['failed_node']
            or binding['physical_proof']['status'] != 'VERIFIED'):
        raise ValueError('Nested fracture alias lacks terminal verified proof')
    with runtime.ledger._write() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS task428_fracture_alias_completions(
            join_id TEXT PRIMARY KEY,child_id TEXT NOT NULL,artifact_sha256 TEXT NOT NULL,
            binding_sha256 TEXT NOT NULL)''')
        for action in ('UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS fracture428_completion_no_{action.lower()}
                BEFORE {action} ON task428_fracture_alias_completions
                BEGIN SELECT RAISE(ABORT,'fracture alias completion is immutable'); END''')
        existing = conn.execute('SELECT child_id,artifact_sha256,binding_sha256 FROM task428_fracture_alias_completions '
                                'WHERE join_id=?', (join_id,)).fetchone()
        exact = (child_id, output['artifact_sha256'], digest(binding))
        if existing:
            if tuple(existing) != exact:
                raise ValueError('Nested fracture completion cannot be rebound')
            return
        old = conn.execute('SELECT * FROM task428_fracture_nodes WHERE child_id=?', (child_id,)).fetchone()
        obsolete = conn.execute('SELECT * FROM task428_obsolete_scopes WHERE scope_id=?', (child_id,)).fetchone()
        if (old is None or old['status'] != 'FRACTURED_OBSOLETE' or obsolete is None
                or obsolete['superseded_by_fracture_id'] != binding['fracture_id']
                or old['lineage_root'] != node['fracture_context']['lineage_root']):
            raise ValueError('Nested alias does not replace this registered obsolete member')
        conn.execute('INSERT INTO task428_fracture_alias_completions VALUES(?,?,?,?)', (join_id, *exact))
        conn.execute("UPDATE task428_fracture_nodes SET status='COMPLETED',artifact_sha256=?,updated_at=? WHERE child_id=?",
                     (output['artifact_sha256'], float(runtime.clock()), child_id))
        siblings = conn.execute('SELECT * FROM task428_fracture_nodes WHERE fracture_id=?', (old['fracture_id'],)).fetchall()
        completed = {item['child_id'] for item in siblings if item['status'] == 'COMPLETED'}
        for sibling in siblings:
            if sibling['status'] != 'BLOCKED_DAG':
                continue
            if set(json.loads(sibling['depends_on_json'])) <= completed:
                next_status = 'HOLD_OWNER_APPROVAL' if sibling['needs_owner_approval'] else 'READY'
                conn.execute('UPDATE task428_fracture_nodes SET status=?,updated_at=? WHERE child_id=?',
                             (next_status, float(runtime.clock()), sibling['child_id']))
