"""Native board review of researched microtask failure boundaries.

This adapter never resumes a terminal board job. A verified pivot changes the
existing lineage; the microtask board then captures a new scoped job. The old
job, original attempts, evidence and accumulated 10/20/30 budget stay intact.
"""
from copy import deepcopy
import json

from . import routing_store as routes
from .pivot_runtime_428 import PivotHoldError, select_pivot_candidates
from .task_routing import digest
from .workflow_428 import _text, assessment


def validate_pivot_review(output):
    fields = {'strategy', 'assessment', 'root_cause_synthesis', 'hypotheses', 'approach', 'fracture_reason'}
    if not isinstance(output, dict) or set(output) != fields or output['strategy'] not in ('pivot', 'fracture'):
        raise ValueError('Pivot review requires an explicit pivot/fracture strategy and complete assessment')
    assessment(output['assessment'])
    _text(output['root_cause_synthesis'], 'Failure synthesis', 8000)
    _text(output['approach'], 'Changed approach', 8000)
    hypotheses = output['hypotheses']
    if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= 20:
        raise ValueError('Pivot review requires 1..20 hypotheses')
    for hypothesis in hypotheses:
        _text(hypothesis, 'Failure hypothesis', 2000)
    reason = output['fracture_reason']
    if not isinstance(reason, str) or '\x00' in reason or len(reason) > 4000:
        raise ValueError('Invalid fracture reason')
    if output['strategy'] == 'fracture' and not reason.strip():
        raise ValueError('Fracture request needs a concrete decomposition reason')
    if output['strategy'] == 'pivot' and reason:
        raise ValueError('A pivot must not carry an ambiguous fracture reason')
    return deepcopy(output)


class PlanningPivotRuntime:
    def __init__(self, journal, store, outcomes, pivot_runtime, fracture_runtime=None):
        self.journal, self.store, self.outcomes, self.pivot_runtime = journal, store, outcomes, pivot_runtime
        from .fracture_runtime_428 import FractureRuntime
        from .planning_fractures_428 import PlanningFractureRuntime
        self.fractures = PlanningFractureRuntime(journal, store, outcomes, fracture_runtime or
            FractureRuntime(pivot_runtime.ledger, pivot_runtime.catalog,
                            dossier_store=outcomes.dossier_store, job_store=store))
        with journal._write() as conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS planning428_pivot_reviews(
                lineage_root TEXT NOT NULL,boundary INTEGER NOT NULL,task_id TEXT NOT NULL,
                source_job_id TEXT NOT NULL,review_job_id TEXT NOT NULL,status TEXT NOT NULL,
                output_sha256 TEXT,selected_profile TEXT,
                PRIMARY KEY(lineage_root,boundary));''')

    def _set_status(self, root, boundary, status, *, output_sha=None, profile=None):
        with self.journal._write() as conn:
            conn.execute('UPDATE planning428_boundaries SET status=? WHERE lineage_root=? AND boundary=?',
                         (status, root, boundary))
            conn.execute('UPDATE planning428_pivot_reviews SET status=?,output_sha256=COALESCE(?,output_sha256),'
                         'selected_profile=COALESCE(?,selected_profile) WHERE lineage_root=? AND boundary=?',
                         (status, output_sha, profile, root, boundary))

    def _source_job(self, root):
        with self.journal._write() as conn:
            refs = [r[0] for r in conn.execute('SELECT reservation_id FROM planning428_observed_outcomes '
                "WHERE lineage_root=? AND disposition='quality_failure' ORDER BY rowid DESC LIMIT 1", (root,))]
        if not refs:
            raise ValueError('Pivot lacks its original quality-failure reservation')
        with self.store._connection() as conn:
            row = conn.execute('SELECT job_id FROM pipeline_route_reservations WHERE reservation_id=?', (refs[0],)).fetchone()
            if row is None:
                raise ValueError('Pivot failure reservation is absent')
            return self.store._get(conn, row[0])

    def _submit_review(self, task_id, boundary):
        from .planning_gateway import prompt_contract, scoped_policy
        root, number = boundary['lineage_root'], boundary['boundary']
        source = self._source_job(root)
        payload = source['payload']
        if payload['planning_intent']['stage'] not in ('MICROTASK_EXECUTION', 'SIMPLE_EXECUTION',
                'SRS', 'REVISING_SRS', 'PLAN_REVIEW', 'WBS', 'MICROTASKS', 'MICROTASK_ASSESSMENT'):
            self._set_status(root, number, 'PIVOT_SCOPE_ADAPTER_REQUIRED')
            return None
        state = self.pivot_runtime.ledger.status(root)
        catalog = payload['task_catalog']
        tier = min(10, state['floor'] + 1)
        tags = payload['planning_intent']['task_types']
        candidates = select_pivot_candidates(catalog, tags, tier, last_failed_model=state['last_model'])
        if not candidates:
            self._set_status(root, number, 'CAPABILITY_HOLD')
            return None
        dossier = self.outcomes.dossier_store.get_dossier(root, number)
        research = self.outcomes.research_runtime.evidence_store.load_for_journal(boundary['research_id'])
        if not dossier or not dossier['research_complete'] or not research:
            raise ValueError('Pivot review requires complete controller-owned failure research')
        task_state = deepcopy(payload['planning_intent']['task'])
        task_state.update(failure_dossier=dossier, failure_research_excerpts=research['excerpts'],
                          failing_microtask=payload.get('microtask_node'),
                          failed_job=dict(job_id=source['job_id'], status=source['status'],
                              error=str(source.get('error') or '')[:8000]))
        intent = dict(schema='cochem-planning-intent/4.2.8', action='model_stage', stage='PIVOT_REVIEW',
            task_id=task_id, version=payload['planning_intent']['version'], state_sha256=digest(task_state),
            catalog_sha256=digest(catalog), srs_sha256=payload['planning_intent']['srs_sha256'],
            complexity=tier, task_types=tags, candidate_profiles=[c['profile_id'] for c in candidates[:5]],
            task=task_state, execution_authorized=False, lineage_root=root, boundary=number,
            failure_dossier_sha256=dossier['dossier_sha256'])
        identity = digest(intent)
        workflow_id, job_id = 'pivot428-' + identity[:40], 'pivot428-node-' + identity[:40]
        request = dict(workflow_type='planning428', planning_intent=intent, task_catalog=catalog,
                       flash_context_limit=payload['flash_context_limit'])
        prompt_contract(request)
        policy = scoped_policy(self.store.routing_policy, intent, catalog)
        with self.store._write() as conn:
            old = conn.execute('SELECT job_id FROM pipeline_jobs WHERE job_id=?', (job_id,)).fetchone()
            if old:
                job = self.store._get(conn, job_id)
                if job['payload'] != request:
                    raise ValueError('Pivot job ID is bound to different captured evidence')
            else:
                self.store._insert(conn, workflow_id, workflow_id, None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS',
                    dict(workflow_type='planning428', intent_sha256=identity))
                routes.capture_workflow(conn, workflow_id, policy)
                self.store._insert(conn, job_id, workflow_id, workflow_id, 'TASK_PLAN', 'PENDING', request, max_attempts=10)
                self.store._event(conn, self.store._get(conn, workflow_id), 'PIVOT_REVIEW_SUBMITTED',
                                 task_id=task_id, lineage_root=root, boundary=number, intent_sha256=identity)
                job = self.store._get(conn, job_id)
        with self.journal._write() as conn:
            conn.execute('INSERT OR IGNORE INTO planning428_pivot_reviews VALUES(?,?,?,?,?,?,NULL,NULL)',
                         (root, number, task_id, source['job_id'], job_id, 'WAITING_FOR_PIVOT_BOARD'))
        self._set_status(root, number, 'WAITING_FOR_PIVOT_BOARD')
        return job

    def step(self, task_id, limit=4):
        from .planning_gateway import PlanningGateway
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError('Pivot review polling must be bounded to 1..8')
        if self.journal.status(task_id)['stage'] == 'CANCELLED':
            return 0
        eligible = {'WAITING_FOR_PIVOT_REVIEW', 'WAITING_FOR_PIVOT_BOARD', 'PIVOT_OWNER_APPROVAL_REQUIRED',
                    'WAITING_FOR_FRACTURE_PLAN', 'WAITING_FOR_FRACTURE_REVIEW', 'FRACTURE_PLAN_REQUIRED',
                    'WAITING_FOR_FRACTURE_PROMOTION'}
        boundaries = [b for b in self.outcomes.status(task_id) if b['status'] in eligible][:limit]
        for boundary in boundaries:
            root, number = boundary['lineage_root'], boundary['boundary']
            if number == 30:
                continue
            with self.journal._write() as conn:
                row = conn.execute('SELECT * FROM planning428_pivot_reviews WHERE lineage_root=? AND boundary=?',
                                   (root, number)).fetchone()
            job = self.store.get(row['review_job_id']) if row else self._submit_review(task_id, boundary)
            if job is None:
                continue
            if job['status'] in ('FAILED', 'BLOCKED'):
                self._set_status(root, number, 'PIVOT_REVIEW_JOB_HELD')
                continue
            if job['status'] != 'COMPLETED':
                continue
            result = PlanningGateway(self.journal, self.store).model_result(job['job_id'])
            if result is None:
                continue
            output = validate_pivot_review(result['output'])
            sha = digest(result)
            source = self.store.get(row['source_job_id']) if row else self._source_job(root)
            if output['strategy'] == 'fracture':
                progress = self.fractures.step(task_id, boundary, source, job, result)
                self._set_status(root, number, progress['status'], output_sha=sha)
                continue
            source_intent = source['payload']['planning_intent']
            captured_runtime = self.pivot_runtime
            if digest(captured_runtime.catalog) != source_intent['catalog_sha256']:
                from .pivot_runtime_428 import PivotRuntime
                captured_runtime = PivotRuntime(self.pivot_runtime.ledger, source['payload']['task_catalog'],
                    dossier_store=self.outcomes.dossier_store)
            state = captured_runtime.ledger.status(root)
            effective_tier = max(output['assessment']['complexity'], min(10, state['floor'] + 1))
            prior_pivot = next((p for p in state['pivots'] if p['after_failures'] == number), None)
            if prior_pivot is not None:
                effective_tier = prior_pivot['proposal']['complexity']
            source_node = job['payload']['planning_intent']['task']['failing_microtask']
            if source_node and effective_tier >= 8:
                from .planning_fractures_428 import validated_child_pivot_scope
                fracture_scope = validated_child_pivot_scope(self.fractures, source)
                approval = self.journal.request_microtask_pivot_approval(task_id, source_intent,
                    lineage_root=root, boundary=number, review_job_id=job['job_id'], review_sha256=sha,
                    classification=dict(output['assessment'], complexity=effective_tier), fracture_scope=fracture_scope)
                receipt = approval.get('owner_approval') or {}
                if not (receipt.get('actor_kind') == 'human_owner' and receipt.get('receipt_id')
                        and receipt.get('request_sha256') == approval['request_sha256']):
                    self._set_status(root, number, 'PIVOT_OWNER_APPROVAL_REQUIRED', output_sha=sha)
                    continue
            # Recover the window after ledger.pivot committed but before our
            # dispatch marker: existing pivot evidence is authoritative.
            existing = captured_runtime.get_pivot_record(root, number)
            if existing is None and any(p['after_failures'] == number
                    for p in captured_runtime.ledger.status(root)['pivots']):
                existing = captured_runtime.recover_pivot_record(root, number)
            if existing is None:
                dossier = self.outcomes.dossier_store.get_dossier(root, number)
                self.outcomes.dossier_store.record_dossier(root, number,
                    research_channels=dossier['research'], root_cause_synthesis=output['root_cause_synthesis'],
                    hypotheses=output['hypotheses'])
                try:
                    review = output['assessment']
                    eligible = select_pivot_candidates(captured_runtime.catalog, review['task_types'], effective_tier,
                                                       last_failed_model=state['last_model'])
                    if source_intent['stage'] == 'PLAN_REVIEW':
                        eligible = [c for c in eligible if c['family'] != source_intent['task']['planner_model']]
                    if not eligible:
                        raise PivotHoldError('CAPABILITY_HOLD', 'No different eligible profile meets review constraints')
                    chosen = captured_runtime.evaluate_pivot(root, task_types=review['task_types'],
                        proposed_complexity=review['complexity'], rationale=review['rationale'] + '\n' + output['approach'],
                        selected_profile_id=eligible[0]['profile_id'])
                    profile = chosen['selected_profile_id']
                except PivotHoldError as error:
                    self._set_status(root, number, error.hold_status, output_sha=sha)
                    continue
            else:
                profile = existing['selected_profile_id']
            committed = captured_runtime.get_pivot_record(root, number)
            context = dict(lineage_root=root, boundary=number, selected_profile_id=profile,
                review_job_id=job['job_id'], review_sha256=sha, approach=output['approach'],
                failure_dossier=self.outcomes.dossier_store.get_dossier(root, number))
            classification = dict(complexity=committed['effective_tier'], task_types=committed['task_types'],
                                  rationale=output['assessment']['rationale'])
            if source_intent['stage'] == 'SIMPLE_EXECUTION':
                self.journal.apply_simple_execution_pivot(task_id, source_intent['version'], source_intent,
                                                         context, classification)
            elif source_intent['stage'] != 'MICROTASK_EXECUTION':
                self.journal.apply_planning_pivot(task_id, source_intent['version'], source_intent,
                                                 context, classification)
            self._set_status(root, number, 'PIVOT_READY_NEW_CAPTURE', output_sha=sha, profile=profile)
        return len(boundaries)

    def dispatch_context(self, root):
        """Return only a controller-accepted reviewed pivot, never an agent-provided route."""
        with self.journal._write() as conn:
            row = conn.execute("SELECT * FROM planning428_pivot_reviews WHERE lineage_root=? "
                "AND status='PIVOT_READY_NEW_CAPTURE' ORDER BY boundary DESC LIMIT 1", (root,)).fetchone()
        if row is None:
            return None
        from .planning_gateway import PlanningGateway
        result = PlanningGateway(self.journal, self.store).model_result(row['review_job_id'])
        if result is None or digest(result) != row['output_sha256']:
            raise ValueError('Pivot dispatch review evidence differs')
        return dict(lineage_root=root, boundary=row['boundary'], selected_profile_id=row['selected_profile'],
            review_job_id=row['review_job_id'], review_sha256=row['output_sha256'],
            approach=result['output']['approach'],
            failure_dossier=self.outcomes.dossier_store.get_dossier(root, row['boundary']))

    def cancellation_targets(self, task_id):
        with self.journal._write() as conn:
            reviews = [row[0] for row in conn.execute('SELECT review_job_id FROM planning428_pivot_reviews WHERE task_id=?',
                                                     (task_id,))]
        return reviews + self.fractures.cancellation_targets(task_id)
