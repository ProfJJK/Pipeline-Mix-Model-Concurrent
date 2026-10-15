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
    for table in ('planning428_budget_members', 'planning428_budget_captures'):
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


def capture_lineage_budget(conn, job_id, payload, policy, *, attempt_ledger, now=None):
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
    _attach_ledger(conn, attempt_ledger)
    root = _resolve_root(conn, member)
    if root is None:
        raise LineageBudgetHold('attempt_lineage_not_initialized')
    row = conn.execute('SELECT state_json FROM planning_budget_ledger.task428_lineages WHERE root=?',
                       (root,)).fetchone()
    state = json.loads(row[0]) if row else {}
    failures = state.get('failures')
    if (state.get('root') != root or state.get('stage') != 'READY' or state.get('research_due')
            or type(failures) is not int or not 0 <= failures < 30):
        raise LineageBudgetHold('quality_research_or_lock_required')
    if payload['planning_intent']['complexity'] < state['floor']:
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
        if old_member and _resolve_root(conn, old_member) == root:
            _map(conn, historical['job_id'], root)
    history = conn.execute('''SELECT r.*,c.total_dispatch_limit AS captured_total,
        c.job_id AS captured_job FROM planning428_budget_members m
        JOIN pipeline_routing_jobs r USING(job_id)
        LEFT JOIN planning428_budget_captures c USING(job_id)
        WHERE m.lineage_root=?''', (root,)).fetchall()
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
    limits = conn.execute('SELECT min(total_dispatch_limit),min(expires_at) '
        'FROM planning428_budget_captures WHERE lineage_root=?', (member[0],)).fetchone()
    if limits[1] is not None and now >= limits[1]:
        return 'lineage_routing_time_exhausted'
    if limits[0] is not None:
        spent = conn.execute('SELECT coalesce(sum(r.dispatches),0) '
            'FROM planning428_budget_members m JOIN pipeline_routing_jobs r USING(job_id) '
            'WHERE m.lineage_root=?', (member[0],)).fetchone()[0]
        if spent >= limits[0]:
            return 'lineage_dispatch_budget_exhausted'
    return None
