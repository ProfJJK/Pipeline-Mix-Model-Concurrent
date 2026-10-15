"""Reopen registered child projections only for accounted physical failures."""
from copy import deepcopy
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
