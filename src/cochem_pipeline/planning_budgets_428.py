"""Controller-only cumulative limits for physical planning generations.

Capture inside the board write transaction, after the existing-job lookup and
before inserting a new job. Initialize/reconcile the quality lineage first,
outside that transaction. This module only reads the attached attempt ledger;
it never resets a lineage or rewrites old immutable routing captures.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
import time

from .planning_outcomes_428 import PlanningOutcomeRuntime
from .routing_store import digest, encoded, policy_dict
from .workflow_428 import AttemptLedger


class LineageBudgetHold(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Planning lineage held: ' + reason)


@dataclass(frozen=True)
class LineageBudget:
    lineage_root: str
    max_attempts: int
    max_dispatches: int | None
    expires_at: float | None
    total_dispatch_limit: int | None
    dispatches_before: int


def _schema(conn):
    # executescript would commit the caller's transaction. Every statement here
    # participates in its existing write transaction, including a failed insert.
    conn.execute('''CREATE TABLE IF NOT EXISTS planning428_budget_members(
        job_id TEXT PRIMARY KEY, lineage_root TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS planning428_budget_captures(
        job_id TEXT PRIMARY KEY, lineage_root TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, policy_sha256 TEXT NOT NULL,
        state_sha256 TEXT NOT NULL, max_attempts INTEGER NOT NULL,
        max_dispatches INTEGER, expires_at REAL, total_dispatch_limit INTEGER,
        dispatches_before INTEGER NOT NULL, created_at REAL NOT NULL,
        CHECK(max_attempts BETWEEN 1 AND 10),
        CHECK(max_dispatches IS NULL OR max_dispatches > 0),
        CHECK(total_dispatch_limit IS NULL OR total_dispatch_limit > 0))''')
    conn.execute('CREATE INDEX IF NOT EXISTS planning428_budget_root '
                 'ON planning428_budget_members(lineage_root)')
    conn.execute('''CREATE TABLE IF NOT EXISTS planning428_budget_ledger_bindings(
        lineage_root TEXT PRIMARY KEY, ledger_path TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS planning428_budget_control_parents(
        lineage_root TEXT PRIMARY KEY, aggregate_root TEXT NOT NULL,
        CHECK(lineage_root != aggregate_root))''')
    for table in ('planning428_budget_members', 'planning428_budget_captures',
                  'planning428_budget_ledger_bindings', 'planning428_budget_control_parents'):
        for operation in ('UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_{operation.lower()}_immutable
                BEFORE {operation} ON {table} BEGIN
                SELECT RAISE(ABORT,'Planning budget capture is immutable'); END''')


def _present(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='planning428_budget_captures'").fetchone() is not None


def _payload_sha(payload):
    # JobStore can append the root's governing requirements during insertion.
    # They do not identify a new physical generation or change its budget.
    return digest({key: value for key, value in payload.items() if key != 'governing_requirements'})


def _result(row):
    return LineageBudget(**{name: row[name] for name in LineageBudget.__dataclass_fields__})


def _attach_ledger(conn, accounting):
    ledger = getattr(accounting, 'ledger', accounting)
    if not isinstance(ledger, AttemptLedger) or not Path(ledger.path).is_file():
        raise LineageBudgetHold('attempt_ledger_unavailable')
    path = Path(ledger.path).resolve()
    attached = {row[1]: row[2] for row in conn.execute('PRAGMA database_list')}
    if 'planning_budget_ledger' in attached:
        if Path(attached['planning_budget_ledger']).resolve() != path:
            raise LineageBudgetHold('attempt_ledger_binding_changed')
    else:
        conn.execute('ATTACH DATABASE ? AS planning_budget_ledger', (str(path),))
    return ledger


def _resolve_root(conn, member):
    row = conn.execute('SELECT root FROM planning_budget_ledger.task428_members '
                       'WHERE task_id=?', (member,)).fetchone()
    return row[0] if row else None


def _map(conn, job_id, root):
    row = conn.execute('SELECT lineage_root FROM planning428_budget_members WHERE job_id=?',
                       (job_id,)).fetchone()
    if row and row[0] != root:
        raise LineageBudgetHold('physical_job_lineage_changed')
    if row is None:
        conn.execute('INSERT INTO planning428_budget_members VALUES(?,?)', (job_id, root))


def _budget_group(conn, root):
    present = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                           "AND name='planning428_budget_control_parents'").fetchone()
    if not present:
        return [root]
    parent = conn.execute('SELECT aggregate_root FROM planning428_budget_control_parents '
                          'WHERE lineage_root=?', (root,)).fetchone()
    aggregate = parent[0] if parent else root
    return [aggregate, *(row[0] for row in conn.execute(
        'SELECT lineage_root FROM planning428_budget_control_parents WHERE aggregate_root=?', (aggregate,)))]


def _bind_control_budget(conn, root, aggregate_root, payload):
    """Controller-only economic link; never merges or reopens quality ledgers."""
    old = conn.execute('SELECT aggregate_root FROM planning428_budget_control_parents '
                       'WHERE lineage_root=?', (root,)).fetchone()
    if old:
        if old[0] != aggregate_root:
            raise LineageBudgetHold('control_budget_parent_changed')
    intent = payload['planning_intent']
    state = intent.get('task') or {}
    declared = state.get('fracture_promotion') or state.get('fracture_scope') or {}
    row = conn.execute('SELECT state_json FROM planning_budget_ledger.task428_lineages WHERE root=?',
                       (aggregate_root,)).fetchone()
    parent = json.loads(row[0]) if row else {}
    if (aggregate_root == root or declared.get('lineage_root') != aggregate_root
            or intent['stage'] not in ('SRS', 'REVISING_SRS', 'PLAN_REVIEW', 'WBS', 'FRACTURE_PLAN', 'FRACTURE_REVIEW')
            or parent.get('failures') not in (10, 20) or parent.get('stage') != 'PIVOT_RESEARCH'
            or not parent.get('research_due') or len(_budget_group(conn, aggregate_root)) > 32
            or _budget_group(conn, aggregate_root)[0] != aggregate_root):
        raise LineageBudgetHold('control_budget_parent_not_due')
    if old:
        return
    if conn.execute('SELECT 1 FROM planning428_budget_members WHERE lineage_root=?', (root,)).fetchone():
        raise LineageBudgetHold('control_budget_parent_requires_fresh_lineage')
    conn.execute('INSERT INTO planning428_budget_control_parents VALUES(?,?)', (root, aggregate_root))


def _compiled_fracture_member(conn, payload, member, root):
    """Lower fragment tiers come from the controller's compiled graph only."""
    node = payload.get('microtask_node') or {}
    declared = node.get('lineage_kind') == 'FAILURE_FRACTURE'
    present = conn.execute("SELECT 1 FROM planning_budget_ledger.sqlite_master "
                          "WHERE type='table' AND name='task428_fracture_nodes'").fetchone()
    row = (conn.execute('SELECT * FROM planning_budget_ledger.task428_fracture_nodes '
                        'WHERE child_id=? AND lineage_root=?', (member, root)).fetchone() if present else None)
    if row is None:
        if declared:
            raise LineageBudgetHold('compiled_fracture_member_missing')
        return False
    intent = payload['planning_intent']
    context = node.get('fracture_context') or {}
    expected_context = dict(fracture_id=row['fracture_id'], graph_sha256=row['graph_sha256'],
        dossier_sha256=row['dossier_sha256'], lineage_root=root, failed_microtask_id=row['failed_scope_id'])
    if (not declared or intent['stage'] != 'MICROTASK_EXECUTION' or intent.get('microtask_id') != member
            or node.get('attempt_lineage_id') != member or context != expected_context
            or intent['complexity'] != row['complexity'] or node.get('complexity') != row['complexity']
            or intent['task_types'] != json.loads(row['task_types_json'])
            or intent['candidate_profiles'] != [row['selected_profile_id']]
            or node.get('role') != row['role'] or row['status'] != 'READY' or row['needs_owner_approval']):
        raise LineageBudgetHold('compiled_fracture_member_mismatch_or_hold')
    for key in ('task_types','requirement_ids','deliverables','depends_on'):
        if node.get(key) != json.loads(row[key+'_json']):
            raise LineageBudgetHold('compiled_fracture_scope_mismatch')
    model = payload['task_catalog']['models'].get(row['selected_profile_id'], {})
    if (model.get('family'), model.get('effort')) != (row['selected_model_family'], row['selected_effort']):
        raise LineageBudgetHold('compiled_fracture_profile_mismatch')
    graph = conn.execute('SELECT graph_json,graph_sha256,dossier_sha256 FROM '
        'planning_budget_ledger.task428_fractures WHERE fracture_id=? AND lineage_root=?',
        (row['fracture_id'], root)).fetchone()
    outbox = conn.execute('SELECT sync_status FROM planning_budget_ledger.task428_fracture_outbox '
                         'WHERE fracture_id=?', (row['fracture_id'],)).fetchone()
    if (graph is None or tuple(graph)[1:] != (row['graph_sha256'], row['dossier_sha256'])
            or outbox is None or outbox[0] != 'COMMITTED'):
        raise LineageBudgetHold('compiled_fracture_graph_uncommitted')
    matches = [child for child in json.loads(graph[0])['children'] if child['id'] == member]
    if len(matches) != 1 or matches[0] != json.loads(row['node_json']):
        raise LineageBudgetHold('compiled_fracture_graph_mismatch')
    for dependency in json.loads(row['depends_on_json']):
        prior = conn.execute('SELECT status,artifact_sha256 FROM planning_budget_ledger.task428_fracture_nodes '
            'WHERE child_id=? AND lineage_root=?', (dependency, root)).fetchone()
        if prior is None or prior[0] != 'COMPLETED' or not prior[1]:
            raise LineageBudgetHold('compiled_fracture_dependencies_pending')
    return row['role'] == 'implementation' and not row['escalated_scope']


def capture_lineage_budget(conn, job_id, payload, policy, *, attempt_ledger, now=None, aggregate_lineage_root=None):
    """Capture remaining finite limits once; never use zero to mean exhausted.

    max_dispatches=None means unlimited, matching routing_store's SQL capture.
    Caller passes the result to capture_workflow(max_dispatches=...) and
    JobStore._insert(max_attempts=...). ensure_job consumes the absolute expiry.
    PIVOT_REVIEW and aggregate swarm jobs have separate control/child accounting
    and must not use an ordinary lineage capture to bypass their research gate.
    """
    if not conn.in_transaction:
        raise ValueError('Planning budget capture requires the board write transaction')
    observed = time.time() if now is None else now
    if type(observed) not in (int, float) or not math.isfinite(observed):
        raise ValueError('Planning budget timestamp must be finite')
    snapshot = policy_dict(policy)
    payload_sha, policy_sha = _payload_sha(payload), digest(snapshot)
    _schema(conn)
    old = conn.execute('SELECT * FROM planning428_budget_captures WHERE job_id=?', (job_id,)).fetchone()
    if old:
        if (old['payload_sha256'], old['policy_sha256']) != (payload_sha, policy_sha):
            raise ValueError('Existing planning budget belongs to different immutable input')
        return _result(old)
    if conn.execute('SELECT 1 FROM pipeline_jobs WHERE job_id=?', (job_id,)).fetchone():
        raise ValueError('Capture planning budget before inserting a new physical job')
    task_id = payload['planning_intent']['task_id']
    member = PlanningOutcomeRuntime.lineage_for_job(task_id, payload)
    if member is None:
        raise LineageBudgetHold('separate_control_or_swarm_accounting_required')
    ledger = _attach_ledger(conn, attempt_ledger)
    root = _resolve_root(conn, member)
    if root is None:
        raise LineageBudgetHold('attempt_lineage_not_initialized')
    if aggregate_lineage_root is not None:
        _bind_control_budget(conn, root, aggregate_lineage_root, payload)
    group = _budget_group(conn, root)
    ledger_path = str(Path(ledger.path).resolve())
    binding = conn.execute('SELECT ledger_path FROM planning428_budget_ledger_bindings '
                           'WHERE lineage_root=?', (root,)).fetchone()
    if binding and binding[0] != ledger_path:
        raise LineageBudgetHold('attempt_ledger_binding_changed')
    if binding is None:
        conn.execute('INSERT INTO planning428_budget_ledger_bindings VALUES(?,?)', (root, ledger_path))
    row = conn.execute('SELECT state_json FROM planning_budget_ledger.task428_lineages WHERE root=?',
                       (root,)).fetchone()
    state = json.loads(row[0]) if row else {}
    failures = state.get('failures')
    if (state.get('root') != root or state.get('stage') != 'READY' or state.get('research_due')
            or type(failures) is not int or not 0 <= failures < 30):
        raise LineageBudgetHold('quality_research_or_lock_required')
    lower_fragment = _compiled_fracture_member(conn, payload, member, root)
    if payload['planning_intent']['complexity'] < state['floor'] and not lower_fragment:
        raise LineageBudgetHold('retained_reasoning_floor')
    expected = (state.get('fracture_child_models') or {}).get(member, state.get('next_model'))
    if expected is not None:
        first = payload['planning_intent']['candidate_profiles'][0]
        if payload['task_catalog']['models'][first]['family'] != expected:
            raise LineageBudgetHold('retained_pivot_model')
    if conn.execute('SELECT 1 FROM planning_budget_ledger.task428_attempts '
                    'WHERE root=? AND result_json IS NULL', (root,)).fetchone():
        raise LineageBudgetHold('quality_attempt_still_active')
    # Adopt historical captures by exact stable lineage, not matching prompts,
    # SRS hashes, retry counters or the physical job ID. WBS siblings stay apart;
    # registered fracture members share their root's one aggregate ceiling.
    rows = conn.execute("SELECT j.job_id,j.payload_json FROM pipeline_jobs j "
        "JOIN pipeline_routing_jobs r USING(job_id) WHERE j.kind='TASK_PLAN' "
        "AND json_extract(j.payload_json,'$.planning_intent.task_id')=?", (task_id,)).fetchall()
    for historical in rows:
        old_payload = json.loads(historical['payload_json'])
        old_member = PlanningOutcomeRuntime.lineage_for_job(task_id, old_payload)
        old_root = _resolve_root(conn, old_member) if old_member else None
        if old_root in group:
            _map(conn, historical['job_id'], old_root)
    history = conn.execute('''SELECT r.*,c.total_dispatch_limit AS captured_total,
        c.job_id AS captured_job FROM planning428_budget_members m
        JOIN pipeline_routing_jobs r USING(job_id)
        LEFT JOIN planning428_budget_captures c USING(job_id)
        WHERE m.lineage_root IN (''' + ','.join('?' for _ in group) + ')', group).fetchall()
    spent = sum(row['dispatches'] for row in history)
    ceilings = [snapshot.get('max_dispatches', 0) or None]
    ceilings.extend(row['captured_total'] if row['captured_job'] else row['max_dispatches'] for row in history)
    finite = [value for value in ceilings if value is not None]
    total = min(finite) if finite else None
    remaining = total - spent if total is not None else None
    if remaining is not None and remaining <= 0:
        raise LineageBudgetHold('lineage_dispatch_budget_exhausted')
    oldest = min([observed, *(row['created_at'] for row in history)])
    deadlines = [row['expires_at'] for row in history if row['expires_at'] is not None]
    seconds = snapshot.get('max_routing_seconds', 0)
    if seconds:
        deadlines.append(oldest + seconds)
    expires = min(deadlines) if deadlines else None
    if expires is not None and observed >= expires:
        raise LineageBudgetHold('lineage_routing_time_exhausted')
    budget = LineageBudget(root, 10 - failures % 10, remaining, expires, total, spent)
    _map(conn, job_id, root)
    conn.execute('''INSERT INTO planning428_budget_captures VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
        (job_id, root, payload_sha, policy_sha, digest(state), budget.max_attempts,
         remaining, expires, total, spent, observed))
    return budget


def insertion_budget(conn, row, payload):
    """Return the controller capture for the first routing insert only."""
    if not _present(conn):
        return None
    capture = conn.execute('SELECT * FROM planning428_budget_captures WHERE job_id=?',
                           (row['job_id'],)).fetchone()
    if capture is None:
        return None
    if (row['kind'] != 'TASK_PLAN' or capture['payload_sha256'] != _payload_sha(payload)
            or capture['policy_sha256'] != digest(json.loads(row['policy_json']))
            or capture['max_attempts'] != row['max_attempts']
            or capture['max_dispatches'] != row['max_dispatches']):
        raise ValueError('Physical planning job differs from its controller budget capture')
    return _result(capture)


def lineage_unavailability(conn, job_id, now):
    """Read-only aggregate guard, also rechecked under the atomic reserve lock."""
    if not _present(conn):
        return None
    member = conn.execute('SELECT lineage_root FROM planning428_budget_members WHERE job_id=?',
                          (job_id,)).fetchone()
    if member is None:
        return None
    group = _budget_group(conn, member[0])
    placeholders = ','.join('?' for _ in group)
    limits = conn.execute('SELECT min(total_dispatch_limit),min(expires_at) '
        f'FROM planning428_budget_captures WHERE lineage_root IN ({placeholders})', group).fetchone()
    if limits[1] is not None and now >= limits[1]:
        return 'lineage_routing_time_exhausted'
    if limits[0] is not None:
        spent = conn.execute('SELECT coalesce(sum(r.dispatches),0) '
            'FROM planning428_budget_members m JOIN pipeline_routing_jobs r USING(job_id) '
            f'WHERE m.lineage_root IN ({placeholders})', group).fetchone()[0]
        if spent >= limits[0]:
            return 'lineage_dispatch_budget_exhausted'
    return _live_quality_hold(conn, job_id, member[0])


def _live_quality_hold(conn, job_id, root):
    """Pending siblings cannot outrun a newly reached research/lock boundary.

    The same board transaction attaches the controller-bound quality database.
    Its rollback journal read lock pins the observed state through reservation;
    it is never inferred from the stale per-job insertion snapshot.
    """
    present = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                           "AND name='planning428_budget_ledger_bindings'").fetchone()
    if present is None:
        return 'attempt_ledger_binding_missing'
    binding = conn.execute('SELECT ledger_path FROM planning428_budget_ledger_bindings '
                          'WHERE lineage_root=?', (root,)).fetchone()
    if binding is None:
        return 'attempt_ledger_binding_missing'
    path = Path(binding[0])
    try:
        if not path.is_absolute() or not path.is_file():
            return 'attempt_ledger_unavailable'
        for item in (path, *path.parents):
            info = item.lstat()
            if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                return 'attempt_ledger_binding_changed'
        attached = {row[1]: row[2] for row in conn.execute('PRAGMA database_list')}
        if 'planning_budget_ledger' in attached:
            if Path(attached['planning_budget_ledger']).resolve() != path.resolve():
                return 'attempt_ledger_binding_changed'
        else:
            # JobStore's connection does not enable URI filenames. A URI here
            # is interpreted as a literal Windows filename and falsely holds
            # every new read-only connection. The private existing path was
            # checked above; this guard executes SELECTs only in that database.
            conn.execute('ATTACH DATABASE ? AS planning_budget_ledger', (str(path),))
        mode = conn.execute('PRAGMA planning_budget_ledger.journal_mode').fetchone()[0]
        if mode not in ('delete', 'truncate', 'persist'):
            return 'attempt_ledger_snapshot_not_fenced'
        group = _budget_group(conn, root)
        if group[0] != root:
            row = conn.execute('SELECT state_json FROM planning_budget_ledger.task428_lineages WHERE root=?',
                               (group[0],)).fetchone()
            parent = json.loads(row[0]) if row else {}
            if (parent.get('stage') != 'PIVOT_RESEARCH' or not parent.get('research_due')
                    or parent.get('failures') not in (10, 20)):
                return 'quality_research_or_lock_required'
        row = conn.execute('SELECT state_json FROM planning_budget_ledger.task428_lineages '
                           'WHERE root=?', (root,)).fetchone()
        state = json.loads(row[0]) if row else {}
        failures = state.get('failures')
        if (state.get('root') == root and state.get('stage') == 'PIVOT_RESEARCH'
                and state.get('research_due') is True and type(failures) is int
                and failures in (10, 20)):
            return 'quality_research_pending'
        if (state.get('root') != root or state.get('stage') != 'READY' or state.get('research_due')
                or type(failures) is not int or not 0 <= failures < 30):
            return 'quality_research_or_lock_required'
        # Outcomes are projected after native cleanup/physical verification.
        # Reserve the remaining potential failure places as well: at 9/19/29
        # failures, four queued siblings must not all launch before the next
        # result is reconciled. This is a temporary capacity wait, not a failure.
        from .attempt_runtime_428 import AVAILABILITY_CATEGORIES
        harmless = sorted(AVAILABILITY_CATEGORIES | {'output_format_correction', 'Cancelled by operator'})
        marks = ','.join('?' for _ in harmless)
        reconciled = conn.execute("SELECT 1 FROM planning_budget_ledger.sqlite_master "
                                  "WHERE type='table' AND name='attempt428_outbox'").fetchone()
        done = ("AND NOT EXISTS (SELECT 1 FROM planning_budget_ledger.attempt428_outbox o "
                "WHERE o.job_id=r.job_id AND o.attempt_id=r.attempt_id AND o.fencing_token=r.fencing_token "
                "AND o.status='RECONCILED')") if reconciled else ''
        outstanding = conn.execute('SELECT count(*) FROM pipeline_route_reservations r '
            'JOIN planning428_budget_members m USING(job_id) WHERE m.lineage_root=? '
            f'AND (r.release_reason IS NULL OR r.release_reason NOT IN ({marks})) ' + done,
            (root, *harmless)).fetchone()[0]
        if outstanding >= 10 - failures % 10:
            return 'quality_window_in_flight'
        job = conn.execute('SELECT payload_json FROM pipeline_jobs WHERE job_id=?', (job_id,)).fetchone()
        payload = json.loads(job[0])
        intent = payload['planning_intent']
        member = PlanningOutcomeRuntime.lineage_for_job(intent['task_id'], payload)
        if _resolve_root(conn, member) != root:
            return 'physical_job_lineage_changed'
        if intent['complexity'] < state['floor']:
            if not _compiled_fracture_member(conn, payload, member, root):
                return 'retained_reasoning_floor'
        expected = (state.get('fracture_child_models') or {}).get(member, state.get('next_model'))
        if expected is not None:
            profiles = intent['candidate_profiles']
            if any(payload['task_catalog']['models'][profile]['family'] != expected for profile in profiles):
                return 'retained_pivot_model'
    except LineageBudgetHold as error:
        return error.reason
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        return 'attempt_ledger_unverified'
    return None
