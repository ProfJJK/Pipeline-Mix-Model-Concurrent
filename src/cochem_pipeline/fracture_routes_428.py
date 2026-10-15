"""Immutable route overlays for already compiled scopes after a reviewed pivot.

The graph, its original classification, completed artifacts and old jobs remain
unchanged. Only a new physical capture can consume an exact overlay, and every
overlay retains the shared lineage's failure/dispatch/time accounting.
"""
from copy import deepcopy
import json

from .pivot_runtime_428 import select_pivot_candidates
from .task_routing import digest


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS task428_fracture_route_amendments(
        amendment_id TEXT PRIMARY KEY,child_id TEXT NOT NULL,boundary INTEGER NOT NULL,
        binding_json TEXT NOT NULL,UNIQUE(child_id,boundary))''')
    for operation in ('UPDATE', 'DELETE'):
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS fracture428_route_no_{operation.lower()}
            BEFORE {operation} ON task428_fracture_route_amendments
            BEGIN SELECT RAISE(ABORT,'fracture route amendment is immutable'); END''')


def effective_registration(conn, registration, *, schema='', amendment_id=None, latest=False):
    """Validate one captured overlay; claim-time callers additionally require latest."""
    if schema not in ('', 'planning_budget_ledger'):
        raise ValueError('Unsupported fracture authority database')
    prefix = schema + '.' if schema else ''
    original = dict(registration)
    present = conn.execute(f"SELECT 1 FROM {prefix}sqlite_master WHERE name='task428_fracture_route_amendments'").fetchone()
    rows = (conn.execute(f'SELECT * FROM {prefix}task428_fracture_route_amendments '
                         'WHERE child_id=? ORDER BY boundary DESC', (original['child_id'],)).fetchall() if present else [])
    if latest and rows and amendment_id != rows[0]['amendment_id']:
        raise ValueError('Fracture route capture is stale')
    if amendment_id is None:
        return original
    matches = [r for r in rows if r['amendment_id'] == amendment_id]
    if len(matches) != 1:
        raise ValueError('Fracture route has no immutable amendment')
    stored = matches[0]
    body = json.loads(stored['binding_json'])
    if (stored['amendment_id'] != 'fractureroute428-' + digest(body)[:40]
            or body['child_id'] != original['child_id'] or body['boundary'] != stored['boundary']
            or body['original_node_sha256'] != digest(json.loads(original['node_json']))
            or any(body[key] != original[key] for key in ('lineage_root', 'fracture_id', 'graph_sha256'))):
        raise ValueError('Fracture route amendment source differs')
    authority = body['authority']
    proof = authority['review_result']
    if digest(proof) != authority['review_sha256'] or proof['job_id'] != authority['review_job_id']:
        raise ValueError('Fracture route review commitment differs')
    if authority['kind'] == 'fracture':
        row = conn.execute(f'SELECT graph_json,graph_sha256 FROM {prefix}task428_fractures '
            'WHERE fracture_id=? AND lineage_root=? AND after_failures=?',
            (authority['fracture_id'], body['lineage_root'], body['boundary'])).fetchone()
        if (row is None or row['graph_sha256'] != authority['graph_sha256']
                or json.loads(row['graph_json'])['review']['review_sha256'] != authority['review_sha256']):
            raise ValueError('Fracture route is not bound to its accepted review')
    elif authority['kind'] == 'pivot':
        row = conn.execute(f'SELECT * FROM {prefix}task428_pivots WHERE lineage_root=? AND boundary=?',
                           (body['lineage_root'], body['boundary'])).fetchone()
        if (row is None or row['selected_profile_id'] != authority['selected_profile_id']
                or row['effective_tier'] != authority['effective_tier']):
            raise ValueError('Fracture route is not bound to its accepted pivot')
    else:
        raise ValueError('Unknown fracture route authority')
    route = body['route']
    if (type(route['complexity']) is not int or not max(original['complexity'], body['floor']) <= route['complexity'] <= 10
            or route['selected_model_family'] == authority['excluded_family']):
        raise ValueError('Fracture route weakens its retained reasoning floor or pivot')
    approval = body.get('owner_approval')
    newly_high = route['complexity'] >= 8 and original['complexity'] < 8
    if newly_high and not (isinstance(approval, dict) and approval.get('actor_kind') == 'human_owner'
                          and approval.get('receipt_id') and approval.get('request_sha256')):
        raise ValueError('High-tier fracture route has no owner approval')
    result = dict(original, **route, task_types_json=json.dumps(body['task_types']),
                  fracture_route_amendment=amendment_id, route_catalog_sha256=body['catalog_sha256'],
                  fracture_route_context=body['dispatch_context'])
    if newly_high:
        result.update(needs_owner_approval=0, owner_approval_json=json.dumps(approval))
    return result


def _accepted_authorities(planner, task_id, records):
    from .planning_gateway import PlanningGateway
    gateway = PlanningGateway(planner.journal, planner.store)
    with planner.journal._write() as conn:
        plan_rows = [dict(r) for r in conn.execute("SELECT * FROM planning428_fracture_plans WHERE task_id=? "
            "AND status='FRACTURE_READY_NEW_CAPTURE'", (task_id,))]
        pivot_rows = ([dict(r) for r in conn.execute("SELECT * FROM planning428_pivot_reviews WHERE task_id=? "
            "AND status='PIVOT_READY_NEW_CAPTURE'", (task_id,))] if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='planning428_pivot_reviews'").fetchone() else [])
        task = planner.journal._read(conn, task_id)
        state, catalog = json.loads(task['state_json']), json.loads(task['catalog_json'])
    authorities = {}
    for row in plan_rows + pivot_rows:
        root, boundary = row['lineage_root'], row['boundary']
        if root in authorities and authorities[root]['boundary'] >= boundary:
            continue
        result = gateway.model_result(row['review_job_id'])
        if result is None:
            raise ValueError('Route amendment review has no cleaned winning output')
        source = planner.store.get(row['source_job_id'])
        source_node = source['payload'].get('microtask_node')
        if source_node is None or not source_node.get('fracture_context'):
            continue  # Original WBS routing is already handled by ordinary pivots.
        if 'fracture_id' in row:
            record = next((r for r in records if r['fracture_id'] == row['fracture_id']), None)
            if record is None or record['graph']['review']['review_sha256'] != digest(result):
                raise ValueError('Route amendment review differs from its committed graph')
            authority = dict(kind='fracture', fracture_id=record['fracture_id'],
                graph_sha256=record['graph_sha256'], excluded_family=record['graph']['last_failed_model'])
        else:
            if row['output_sha256'] != digest(result):
                raise ValueError('Route amendment review differs from its committed pivot')
            with planner.fracture_runtime.ledger._write() as conn:
                pivot = conn.execute('SELECT * FROM task428_pivots WHERE lineage_root=? AND boundary=?', (root,boundary)).fetchone()
            if pivot is None or row['selected_profile'] != pivot['selected_profile_id']:
                raise ValueError('Route amendment pivot profile differs')
            dossier = planner.outcomes.dossier_store.get_dossier(root, boundary)
            authority = dict(kind='pivot', selected_profile_id=pivot['selected_profile_id'],
                effective_tier=pivot['effective_tier'], excluded_family=dossier['last_failed_model'])
        authorities[root] = dict(authority, boundary=boundary, review_result=result,
            review_job_id=row['review_job_id'], review_sha256=digest(result),
            source_job_id=source['job_id'], source_child_id=source_node['microtask_id'],
            failure_dossier=planner.outcomes.dossier_store.get_dossier(root, boundary))
    return authorities, state, catalog


def amend_records(planner, task_id, records):
    """Capture reviewed route overlays before the board constructs new jobs."""
    authorities, task_state, catalog = _accepted_authorities(planner, task_id, records)
    ledger = planner.fracture_runtime.ledger
    with ledger._write() as conn:
        initialize(conn)
        for record in records:
            root = record['lineage_root']
            authority = authorities.get(root)
            if authority is None:
                continue
            state = ledger._read(conn, root)
            if state['stage'] != 'READY' or state['research_due']:
                continue
            for child in record['children']:
                row = conn.execute('SELECT * FROM task428_fracture_nodes WHERE child_id=?', (child['child_id'],)).fetchone()
                if row['status'] in ('COMPLETED', 'FRACTURED_OBSOLETE'):
                    continue
                specific = authority['kind'] == 'pivot' and authority['source_child_id'] == row['child_id']
                if not specific and (row['role'] == 'implementation' or row['complexity'] >= state['floor']):
                    continue
                previous = conn.execute('SELECT * FROM task428_fracture_route_amendments WHERE child_id=? AND boundary=?',
                                        (row['child_id'], authority['boundary'])).fetchone()
                if previous:
                    continue
                tags = (authority['review_result']['output']['assessment']['task_types'] if specific
                        else json.loads(row['task_types_json']))
                tier = max(row['complexity'], state['floor'], authority.get('effective_tier', 1) if specific else 1)
                candidates = select_pivot_candidates(catalog, tags, tier,
                    last_failed_model=authority['excluded_family'])
                if specific:
                    candidates = [c for c in candidates if c['profile_id'] == authority['selected_profile_id']]
                if not candidates:
                    raise ValueError('Reviewed fracture route has no eligible profile')
                approval = None
                if tier >= 8 and row['complexity'] < 8:
                    pending = (task_state.get('microtask_pivot_approvals') or {}).get(root) or {}
                    approval = pending.get('owner_approval')
                    if (not specific or pending.get('microtask_id') != row['child_id']
                            or pending.get('review_sha256') != authority['review_sha256']
                            or not approval or approval.get('request_sha256') != pending.get('request_sha256')):
                        # Preserve the original scope and leave dispatch held at
                        # its retained floor until a matching owner decision.
                        continue
                selected = candidates[0]
                route = dict(complexity=tier, selected_profile_id=selected['profile_id'],
                    selected_model_family=selected['family'], selected_effort=selected['effort'])
                body = dict(schema='cochem-fracture-route-amendment/4.2.8', child_id=row['child_id'],
                    lineage_root=root, fracture_id=row['fracture_id'], graph_sha256=row['graph_sha256'],
                    original_node_sha256=digest(json.loads(row['node_json'])), boundary=authority['boundary'],
                    floor=state['floor'], task_types=tags, route=route, authority=authority, owner_approval=approval,
                    catalog_sha256=digest(catalog), dispatch_context=dict(
                        schema='cochem-fracture-reviewed-route/4.2.8', boundary=authority['boundary'],
                        review_job_id=authority['review_job_id'], review_sha256=authority['review_sha256'],
                        reviewed_output=authority['review_result']['output'],
                        failure_dossier=authority['failure_dossier']))
                amendment_id = 'fractureroute428-' + digest(body)[:40]
                conn.execute('INSERT INTO task428_fracture_route_amendments VALUES(?,?,?,?)',
                             (amendment_id,row['child_id'],authority['boundary'],json.dumps(body,sort_keys=True)))
                effective_registration(conn,row,amendment_id=amendment_id,latest=True)
                state.setdefault('fracture_child_models', {})[row['child_id']] = selected['family']
            ledger._save(conn, state)
        result = deepcopy(records)
        for record in result:
            for child in record['graph']['children']:
                row = conn.execute('SELECT * FROM task428_fracture_nodes WHERE child_id=?', (child['id'],)).fetchone()
                latest = conn.execute('SELECT amendment_id FROM task428_fracture_route_amendments '
                    'WHERE child_id=? ORDER BY boundary DESC LIMIT 1', (child['id'],)).fetchone()
                if latest is None:
                    continue
                effective = effective_registration(conn,row,amendment_id=latest[0],latest=True)
                child.update({key: effective[key] for key in ('complexity','selected_profile_id','selected_model_family',
                                                            'selected_effort','fracture_route_amendment',
                                                            'fracture_route_context')})
                child['task_types'] = json.loads(effective['task_types_json'])
                projection = next(r for r in record['children'] if r['child_id'] == child['id'])
                projection.update(needs_owner_approval=bool(effective['needs_owner_approval']),
                    owner_approval=json.loads(effective['owner_approval_json']) if effective['owner_approval_json'] else None)
        return result
