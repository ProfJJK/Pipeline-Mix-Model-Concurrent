"""Bounded reconciliation of actual native reservations into planning lineages.

Only the board's reserved identity, released outcome and cleanup record can be
consumed here. Format correction, cancellation and unavailable providers are
not quality failures. No board jobs or native processes are started here.
"""
from __future__ import annotations

import json

from .attempt_runtime_428 import classify_attempt_outcome
from .task_routing import digest
from .workflow_428 import _id


class PlanningOutcomeRuntime:
    def __init__(self, journal, store, accounting, *, research_runtime=None,
                 dossier_store=None, decision_store=None, artifact_runtime=None):
        self.journal, self.store, self.accounting = journal, store, accounting
        self.research_runtime, self.dossier_store = research_runtime, dossier_store
        self.decision_store = decision_store
        self.artifact_runtime = artifact_runtime
        with journal._write() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS planning428_observed_outcomes(
                    reservation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    lineage_root TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
                    disposition TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS planning428_boundaries(
                    lineage_root TEXT NOT NULL, boundary INTEGER NOT NULL,
                    task_id TEXT NOT NULL, research_id TEXT, status TEXT NOT NULL,
                    dossier_sha256 TEXT, PRIMARY KEY(lineage_root,boundary));
            ''')

    @staticmethod
    def lineage_for_job(task_id, payload):
        intent = payload['planning_intent']
        if intent['task_id'] != task_id:
            raise ValueError('Outcome belongs to another planning task')
        if intent.get('attempt_lineage_id'):
            return _id(intent['attempt_lineage_id'])
        if intent['stage'] in ('MICROTASK_SWARM_BATCH', 'PIVOT_REVIEW', 'FRACTURE_PLAN', 'FRACTURE_REVIEW'):
            # Individual outcomes are fenced by complete_swarm_batch; charging
            # this aggregate reservation would double-charge its children.
            return None
        node = payload.get('microtask_node')
        if node is not None:
            return _id(node['attempt_lineage_id'])
        if intent['stage'] == 'SIMPLE_EXECUTION':
            return _id(task_id)
        return _id('plan428-' + digest({'task_id': task_id, 'stage': intent['stage']})[:40])

    def reconcile_task(self, task_id, *, limit=64):
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError('Outcome reconciliation must be bounded to 1..128 reservations')
        _id(task_id)
        with self.store._connection() as conn:
            # Attach only for this read query, so LIMIT bounds rows transferred
            # even when the durable history contains many earlier reservations.
            conn.execute('ATTACH DATABASE ? AS observed_outcomes', (str(self.journal.path),))
            rows = conn.execute('SELECT r.* FROM pipeline_route_reservations r '
                'JOIN pipeline_jobs j ON j.job_id=r.job_id WHERE r.released_at IS NOT NULL '
                "AND j.kind='TASK_PLAN' AND json_extract(j.payload_json,'$.planning_intent.task_id')=? "
                'AND NOT EXISTS(SELECT 1 FROM observed_outcomes.planning428_observed_outcomes o '
                'WHERE o.reservation_id=r.reservation_id) '
                'ORDER BY r.reserved_at,r.rowid LIMIT ?', (task_id, limit))
            pending = [dict(row) for row in rows]
        count = 0
        for reservation in pending:
            physical = None
            with self.store._connection() as conn:
                job = self.store._get(conn, reservation['job_id'])
                cleanup = conn.execute('SELECT cleared_at FROM pipeline_execution_cleanup '
                    'WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                    (job['job_id'], reservation['attempt_id'], reservation['fencing_token'])).fetchone()
            if cleanup is None or cleanup[0] is None:
                # Keep this earlier lineage attempt ahead of later fences.
                break
            payload = job['payload']
            lineage = self.lineage_for_job(task_id, payload)
            if lineage is None:
                disposition = ('PIVOT_REVIEW_CONTROL' if payload['planning_intent']['stage'] == 'PIVOT_REVIEW'
                               else 'SWARM_CHILD_ACCOUNTING')
                lineage = task_id
            else:
                reason = reservation['release_reason']
                if reason == 'output_format_correction':
                    disposition = 'FORMAT_CORRECTION_NOT_QUALITY'
                elif reason == 'Cancelled by operator':
                    disposition = 'CANCELLED_NOT_QUALITY'
                elif reason == 'completed':
                    receipt = job.get('receipt') or {}
                    if (job['status'] != 'COMPLETED' or receipt.get('attempt_id') != reservation['attempt_id']
                            or receipt.get('fencing_token') != reservation['fencing_token']
                            or receipt.get('route_reservation_id') != reservation['reservation_id']):
                        raise ValueError('Completed reservation has no matching committed receipt')
                    disposition = 'success'
                    from .task_artifact_runtime_428 import TaskArtifactRuntime
                    if TaskArtifactRuntime.requires_terminal_verification(payload):
                        if self.artifact_runtime is None:
                            continue
                        physical = self.artifact_runtime.verification_outcome(job)
                        if physical['status'] == 'TASK_VERIFICATION_CANCELLED':
                            disposition = 'CANCELLED_NOT_QUALITY'
                        elif physical['status'] not in ('VERIFIED', 'REJECTED'):
                            # A model proposal is not yet a completed external
                            # result. Infrastructure holds do not spend quality.
                            continue
                        else:
                            disposition = 'success' if physical['status'] == 'VERIFIED' else 'quality_failure'
                else:
                    try:
                        disposition = classify_attempt_outcome(reason)
                    except ValueError:
                        # Unknown cancellation/infrastructure reasons never
                        # become an invented quality charge.
                        disposition = 'UNCLASSIFIED_RELEASE_HOLD'
            evidence = dict(reservation_id=reservation['reservation_id'], job_id=job['job_id'],
                attempt_id=reservation['attempt_id'], fencing_token=reservation['fencing_token'],
                release_reason=reservation['release_reason'], cleanup_verified=True,
                receipt=job.get('receipt') if reservation['release_reason'] == 'completed' else None)
            if physical is not None:
                evidence['physical_verification'] = physical
            sha = digest(evidence)
            if disposition in ('success', 'quality_failure', 'availability'):
                catalog = payload['task_catalog']
                route = json.loads(reservation['route_json'])
                profiles = [catalog['models'][key] for key in payload['planning_intent']['candidate_profiles']
                    if all(catalog['models'][key][a] == route[b] for a, b in
                           (('provider', 'provider'), ('model', 'model'), ('effort', 'reasoning_effort')))]
                if len(profiles) != 1:
                    raise ValueError('Reserved model does not match exactly one captured task profile')
                state = self.accounting.ensure_lineage(lineage,
                    complexity=payload['planning_intent']['complexity'])
                root = state['root']
                self.accounting.start_board_attempt(job['job_id'], reservation['attempt_id'],
                    reservation['fencing_token'], lineage_root=root, member_id=lineage,
                    model_family=profiles[0]['family'], complexity=payload['planning_intent']['complexity'])
                state = self.accounting.record_board_outcome(job['job_id'], reservation['attempt_id'],
                    reservation['fencing_token'], category=disposition, evidence_sha256=sha)
                # Fracture members share the original root. Boundary source
                # discovery must find their exact failures under that root.
                lineage = root
                if state['research_due']:
                    self._boundary(task_id, state, payload)
            with self.journal._write() as conn:
                conn.execute('INSERT OR IGNORE INTO planning428_observed_outcomes VALUES(?,?,?,?,?)',
                    (reservation['reservation_id'], task_id, lineage, sha, disposition))
            count += 1
        self._research_boundaries(task_id)
        return count

    def _boundary(self, task_id, state, payload):
        boundary, root = state['failures'], state['root']
        with self.journal._write() as conn:
            conn.execute('INSERT OR IGNORE INTO planning428_boundaries VALUES(?,?,?,?,?,NULL)',
                (root, boundary, task_id, None, 'WAITING_FOR_FAILURE_RESEARCH'))
        if self.research_runtime is None or self.dossier_store is None:
            return
        failures = self.dossier_store._committed_quality_failures(root)
        # Bind research to the exact failed window, not a previous successful SRS search.
        intent = dict(schema='cochem-planning-intent/4.2.8', action='controller_research',
            task_id='failure428-' + digest({'root': root, 'boundary': boundary})[:40],
            stage='FAILURE_RESEARCH', srs_sha256=digest(failures[-10:]),
            query=(payload['planning_intent']['task']['objective'][:1500] +
                   ' Diagnose repeated verification failures and alternative implementation approaches.'),
            channels=['internet', 'wiki_rag', 'papers'])
        request = self.research_runtime.enqueue(intent)
        with self.journal._write() as conn:
            conn.execute('UPDATE planning428_boundaries SET research_id=? WHERE lineage_root=? AND boundary=?',
                         (request['research_id'], root, boundary))

    def _research_boundaries(self, task_id):
        if self.research_runtime is None or self.dossier_store is None:
            return
        with self.journal._write() as conn:
            boundaries = conn.execute('SELECT * FROM planning428_boundaries WHERE task_id=? '
                "AND status='WAITING_FOR_FAILURE_RESEARCH' ORDER BY boundary LIMIT 8", (task_id,)).fetchall()
        for row in boundaries:
            if not row['research_id']:
                continue
            result = self.research_runtime.evidence_store.load_for_journal(row['research_id'])
            if result is None:
                continue
            dossier = self.dossier_store.record_dossier(row['lineage_root'], row['boundary'],
                research_channels=result['channels'],
                root_cause_synthesis='Ten committed quality failures; exact reservation evidence retained. '
                    'Root causes remain hypotheses until independent model evaluation.',
                hypotheses=['Review the retained failed outputs and verification diagnostics against the '
                    'requirement scope; propose a changed approach or a narrower decomposition.'])
            status = ('WAITING_FOR_PIVOT_REVIEW' if dossier['research_complete'] else 'PIVOT_RESEARCH_HOLD')
            if row['boundary'] == 30:
                status = 'LOCKED_AWAITING_OWNER' if dossier['research_complete'] else 'PIVOT_RESEARCH_HOLD'
            with self.journal._write() as conn:
                conn.execute('UPDATE planning428_boundaries SET status=?,dossier_sha256=? '
                    'WHERE lineage_root=? AND boundary=?',
                    (status, dossier['dossier_sha256'], row['lineage_root'], row['boundary']))

    def status(self, task_id):
        with self.journal._write() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM planning428_boundaries '
                'WHERE task_id=? ORDER BY lineage_root,boundary', (task_id,))]

    def unresolved_releases(self, task_id):
        with self.journal._write() as conn:
            return [dict(row) for row in conn.execute('SELECT reservation_id,evidence_sha256,disposition '
                "FROM planning428_observed_outcomes WHERE task_id=? AND disposition='UNCLASSIFIED_RELEASE_HOLD' "
                'ORDER BY reservation_id LIMIT 16', (task_id,))]
