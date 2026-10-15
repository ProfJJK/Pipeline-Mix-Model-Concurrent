"""Receipt-bound fracture planning and independent review on the normal board."""
from copy import deepcopy
import json

from . import routing_store as routes
from .fracture_runtime_428 import FractureRuntime
from .pivot_runtime_428 import select_pivot_candidates, PivotHoldError
from .planning_budgets_428 import capture_lineage_budget, LineageBudgetHold
from .task_routing import digest
from .workflow_428 import _dag, _id, _text, _texts, assessment


def validated_fracture_source(planner, task_id, fracture_record):
    """Rebind an accepted graph to the original immutable failed job contract."""
    with planner.journal._write() as conn:
        rows = conn.execute('SELECT source_job_id,boundary,lineage_root FROM planning428_fracture_plans '
            "WHERE task_id=? AND fracture_id=? AND status='FRACTURE_READY_NEW_CAPTURE'",
            (task_id, fracture_record['fracture_id'])).fetchall()
    if len(rows) != 1:
        raise ValueError('Fracture has no unique accepted source capture')
    row = rows[0]
    record = planner.fracture_runtime.accepted_record(row['lineage_root'], row['boundary'])
    if record is None or any(record[key] != fracture_record.get(key)
            for key in ('fracture_id', 'lineage_root', 'failed_scope_id', 'graph_sha256')):
        raise ValueError('Fracture source has no matching committed graph')
    source = planner.store.get(row['source_job_id'])
    payload = source['payload']
    if (payload['planning_intent']['task_id'] != task_id
            or payload['microtask_node']['microtask_id'] != record['failed_scope_id']
            or planner.fracture_runtime.ledger.status(payload['microtask_node']['attempt_lineage_id'])['root'] != record['lineage_root']):
        raise ValueError('Fracture source belongs to another failed scope or shared lineage')
    return source


def validated_external_predecessors(planner, payload):
    """Return only original dependency captures bound to this registered fracture."""
    node = payload.get('microtask_node') or {}
    context = node.get('fracture_context')
    supplied = node.get('fracture_external_predecessors') or {}
    if context is None:
        if supplied:
            raise ValueError('External fracture dependencies require a compiled graph')
        return {}
    intent = payload['planning_intent']
    with planner.journal._write() as conn:
        rows = conn.execute('SELECT source_job_id,boundary,lineage_root FROM planning428_fracture_plans '
            "WHERE task_id=? AND fracture_id=? AND status='FRACTURE_READY_NEW_CAPTURE'",
            (intent['task_id'], context['fracture_id'])).fetchall()
    if len(rows) != 1:
        raise ValueError('Fracture has no unique accepted source capture')
    row = rows[0]
    record = planner.fracture_runtime.accepted_record(row['lineage_root'], row['boundary'])
    if record is None:
        raise ValueError('Fracture source has no committed graph')
    expected_context = dict(fracture_id=record['fracture_id'], graph_sha256=record['graph_sha256'],
        dossier_sha256=record['dossier_sha256'], lineage_root=record['lineage_root'],
        failed_microtask_id=record['failed_scope_id'])
    if context != expected_context or node['microtask_id'] not in {child['id'] for child in record['graph']['children']}:
        raise ValueError('External dependencies belong to another compiled child')
    source = planner.store.get(row['source_job_id'])['payload']
    if (source['planning_intent']['task_id'] != intent['task_id']
            or source['planning_intent']['plan_generation_sha256'] != intent['plan_generation_sha256']
            or source['microtask_node']['microtask_id'] != record['failed_scope_id']):
        raise ValueError('External dependencies belong to another failed scope or generation')
    expected = source.get('predecessor_outputs') or {}
    if supplied != expected:
        raise ValueError('Fracture external dependency capture changed')
    return deepcopy(expected)


def validated_child_pivot_scope(planner, source):
    """Bind a high-tier pivot approval to its actual registered failed child."""
    payload = source['payload']
    node, intent = payload['microtask_node'], payload['planning_intent']
    context = node.get('fracture_context')
    if context is None:
        return None
    if intent['microtask_id'] != node['microtask_id']:
        raise ValueError('Child pivot intent and captured scope differ')
    validated_external_predecessors(planner, payload)
    child = planner.fracture_runtime.get_fracture_child(node['microtask_id'])
    if (child['fracture_id'] != context['fracture_id'] or child['graph_sha256'] != context['graph_sha256']
            or child['lineage_root'] != context['lineage_root']
            or node['attempt_lineage_id'] != child['child_id'] or child['status'] == 'FRACTURED_OBSOLETE'
            or planner.fracture_runtime.ledger.status(node['attempt_lineage_id'])['root'] != child['lineage_root']):
        raise ValueError('Child pivot must retain its compiled shared lineage')
    return dict(fracture_id=context['fracture_id'], graph_sha256=context['graph_sha256'],
        dossier_sha256=context['dossier_sha256'], lineage_root=context['lineage_root'], child_id=node['microtask_id'],
        source_job_id=source['job_id'], source_intent_sha256=digest(intent), source_node_sha256=digest(node),
        plan_generation_sha256=intent['plan_generation_sha256'])


def validate_fracture_plan(payload, output):
    if not isinstance(output, dict) or set(output) != {'summary', 'children'}:
        raise ValueError('Fracture plan requires summary and children')
    _text(output['summary'], 'Fracture summary', 8000)
    children = output['children']
    if not isinstance(children, list) or not 4 <= len(children) <= 32:
        raise ValueError('Fracture needs 4..32 bounded children including assembly and final test')
    scope = payload['planning_intent']['task']['fracture_scope']
    reqs, implementations, assemblies, finals = set(scope['requirement_ids']), [], [], []
    covered, signatures = set(), set()
    for child in children:
        if not isinstance(child, dict) or set(child) != {'id', 'role', 'complexity', 'task_types',
                'rationale', 'requirement_ids', 'deliverables', 'release_criteria', 'depends_on', 'prompt', 'audit_metrics'}:
            raise ValueError('Fracture children need exact typed scope, classification, prompt and checks')
        _id(child['id'])
        assessment({key: child[key] for key in ('complexity', 'task_types', 'rationale')})
        child_reqs = set(_texts(child['requirement_ids'], 'Child requirements'))
        if child_reqs - reqs:
            raise ValueError('Fracture child expands the failed requirement scope')
        for field in ('deliverables', 'release_criteria', 'audit_metrics'):
            _texts(child[field], field)
        _text(child['prompt'], 'Child prompt', 16000)
        if child['role'] == 'implementation':
            signature = (tuple(sorted(child_reqs)), tuple(sorted(child['deliverables'])))
            if signature in signatures:
                raise ValueError('Duplicate implementation fragment scope')
            signatures.add(signature)
            if (len(reqs) > 1 and child_reqs == reqs and len(scope['deliverables']) > 1
                    and set(child['deliverables']) == set(scope['deliverables'])):
                raise ValueError('Implementation fragment must be narrower than failed scope')
            implementations.append(child)
            covered |= child_reqs
        elif child['role'] == 'assembly':
            assemblies.append(child)
        elif child['role'] == 'final_test':
            finals.append(child)
        else:
            raise ValueError('Unsupported fracture child role')
    if len(implementations) < 2 or len(assemblies) != 1 or len(finals) != 1 or covered != reqs:
        raise ValueError('Fracture needs covering implementation fragments, exactly one assembly and final test')
    ancestors = _dag(children)
    impl_ids = {child['id'] for child in implementations}
    assembly, final = assemblies[0], finals[0]
    floor = max(min(10, scope['parent_floor'] + 1), scope.get('minimum_assembly_complexity', 1))
    if (not impl_ids <= ancestors[assembly['id']] or assembly['id'] not in ancestors[final['id']]
            or any(set(child['requirement_ids']) != reqs for child in (assembly, final))
            or any(child['complexity'] < floor for child in (assembly, final))
            or any(not set(scope['release_criteria']) <= set(child['release_criteria']) for child in (assembly, final))
            or not set(scope['deliverables']) <= set((final if scope.get('failed_role') == 'final_test' else assembly)['deliverables'])
            or not set().union(*(set(child['deliverables']) for child in implementations)) <= set(assembly['deliverables'])):
        raise ValueError('Fracture assembly and final test must preserve full scope, dependency order and raised floor')
    return deepcopy(output)


def validate_fracture_review(payload, output):
    if (not isinstance(output, dict) or set(output) != {'accepted', 'plan_sha256', 'findings'}
            or type(output['accepted']) is not bool
            or output['plan_sha256'] != payload['planning_intent']['fracture_plan_sha256']
            or not isinstance(output['findings'], list) or len(output['findings']) > 40):
        raise ValueError('Fracture review must decide the exact captured plan')
    for finding in output['findings']:
        _text(finding, 'Fracture review finding', 4000)
    if not output['accepted'] and not output['findings']:
        raise ValueError('Rejected fracture needs actionable findings')
    return deepcopy(output)


def fracture_contract(payload):
    intent = payload['planning_intent']
    if intent['stage'] == 'FRACTURE_REVIEW':
        return dict(accepted=True, plan_sha256=intent['fracture_plan_sha256'], findings=[])
    scope = intent['task']['fracture_scope']
    reqs = scope['requirement_ids']
    floor = max(min(10, scope['parent_floor'] + 1), scope.get('minimum_assembly_complexity', 1))
    assembly_paths = ([] if scope.get('failed_role') == 'final_test' else scope['deliverables']) + ['fragment-a.txt', 'fragment-b.txt']
    final_paths = scope['deliverables'] if scope.get('failed_role') == 'final_test' else ['verification.txt']
    def child(cid, role, tier, paths, deps):
        return dict(id=cid, role=role, complexity=tier, task_types=intent['task_types'],
            rationale='Independent scoped assessment', requirement_ids=reqs,
            deliverables=paths, release_criteria=scope['release_criteria'], depends_on=deps,
            prompt='Self-contained task with exact interface and expected output', audit_metrics=['Exact requirement check'])
    return dict(summary='Decompose the observed failure while preserving every requirement', children=[
        child('fragment-a', 'implementation', 3, ['fragment-a.txt'], []),
        child('fragment-b', 'implementation', 3, ['fragment-b.txt'], []),
        child('assembly', 'assembly', floor, list(dict.fromkeys(assembly_paths)), ['fragment-a', 'fragment-b']),
        child('final-test', 'final_test', floor, final_paths, ['assembly'])])


class PlanningFractureRuntime:
    def __init__(self, journal, store, outcomes, fracture_runtime):
        self.journal, self.store, self.outcomes = journal, store, outcomes
        self.fracture_runtime = fracture_runtime
        with journal._write() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS planning428_fracture_plans(
                lineage_root TEXT NOT NULL,boundary INTEGER NOT NULL,task_id TEXT NOT NULL,
                source_job_id TEXT NOT NULL,pivot_job_id TEXT NOT NULL,plan_job_id TEXT NOT NULL,
                review_job_id TEXT,status TEXT NOT NULL,fracture_id TEXT,
                PRIMARY KEY(lineage_root,boundary))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS planning428_fracture_controls(
                job_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,lineage_root TEXT NOT NULL,
                boundary INTEGER NOT NULL,stage TEXT NOT NULL)''')

    def _submit(self, source, *, stage, task_state, tier, tags, candidates, extra=None):
        from .planning_gateway import prompt_contract, scoped_policy
        original = source['payload']['planning_intent']
        intent = dict(schema='cochem-planning-intent/4.2.8', action='model_stage', stage=stage,
            task_id=original['task_id'], version=original['version'], state_sha256=digest(task_state),
            catalog_sha256=original['catalog_sha256'], srs_sha256=task_state.get('srs_sha256', original['srs_sha256']), task=task_state,
            complexity=tier, task_types=tags, candidate_profiles=[item['profile_id'] for item in candidates[:5]],
            execution_authorized=False, **(extra or {}))
        intent['attempt_lineage_id'] = 'fracture-control428-' + digest(dict(task=original['task_id'],
            root=task_state['fracture_scope']['lineage_root'], stage=stage))[:36]
        key = digest(intent)
        root_id, job_id = 'fracture-plan428-' + key[:36], 'fracture-node428-' + key[:36]
        payload = dict(workflow_type='planning428', planning_intent=intent,
                       task_catalog=source['payload']['task_catalog'], flash_context_limit=source['payload']['flash_context_limit'])
        prompt_contract(payload)
        policy = scoped_policy(self.store.routing_policy, intent, payload['task_catalog'])
        accounting = self.outcomes.accounting
        accounting.ensure_lineage(intent['attempt_lineage_id'], complexity=tier)
        with self.store._write() as conn:
            old = conn.execute('SELECT 1 FROM pipeline_jobs WHERE job_id=?', (job_id,)).fetchone()
            if old:
                result = self.store._get(conn, job_id)
                if result['payload'] != payload:
                    raise ValueError('Fracture control capture cannot be rebound')
            else:
                budget = capture_lineage_budget(conn, job_id, payload, policy, attempt_ledger=accounting,
                    aggregate_lineage_root=task_state['fracture_scope']['lineage_root'])
                self.store._insert(conn, root_id, root_id, None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS',
                                   dict(workflow_type='planning428', intent_sha256=key))
                routes.capture_workflow(conn, root_id, policy, max_dispatches=budget.max_dispatches)
                self.store._insert(conn, job_id, root_id, root_id, 'TASK_PLAN', 'PENDING', payload,
                                   max_attempts=budget.max_attempts)
                result = self.store._get(conn, job_id)
        with self.journal._write() as conn:
            conn.execute('INSERT OR IGNORE INTO planning428_fracture_controls VALUES(?,?,?,?,?)',
                (job_id, original['task_id'], task_state['fracture_scope']['lineage_root'],
                 task_state['failure_dossier']['boundary'], stage))
        return result

    def step(self, task_id, boundary, source, pivot_job, pivot_result):
        from .planning_gateway import PlanningGateway
        from .fracture_promotion_428 import begin_promotion, promotion_scope, activate_promotion
        root, number = boundary['lineage_root'], boundary['boundary']
        source_intent, failed = source['payload']['planning_intent'], source['payload'].get('microtask_node')
        if self.journal.status(task_id)['stage'] == 'CANCELLED':
            return dict(status='FRACTURE_CANCELLED')
        captured = self.fracture_runtime
        if digest(captured.catalog) != source_intent['catalog_sha256']:
            captured = FractureRuntime(captured.ledger, source['payload']['task_catalog'],
                dossier_store=captured.dossier_store, job_store=self.store)
        with self.journal._write() as conn:
            row = conn.execute('SELECT * FROM planning428_fracture_plans WHERE lineage_root=? AND boundary=?',
                               (root, number)).fetchone()
        if row and row['fracture_id']:
            accepted = captured.accepted_record(root, number)
            if accepted is None or accepted['fracture_id'] != row['fracture_id']:
                raise ValueError('Fracture projection has no committed graph')
            if not failed:
                activate_promotion(self.journal, task_id, accepted)
            return dict(status='FRACTURE_READY_NEW_CAPTURE', fracture_id=row['fracture_id'])
        ledger = captured.ledger.status(root)
        if not failed:
            task_state = begin_promotion(self.journal, task_id, boundary, source, pivot_job, pivot_result,
                ledger, self.outcomes.dossier_store.get_dossier(root, number))
            if task_state['stage'] != 'FRACTURE_PROMOTION_READY':
                return dict(status='WAITING_FOR_FRACTURE_PROMOTION', stage=task_state['stage'])
            # A graph commit can precede its projection; retain the original
            # plan scope instead of demanding that the now-READY ledger reopen.
            scope = (self.store.get(row['plan_job_id'])['payload']['planning_intent']['task']['fracture_scope']
                     if row else promotion_scope(task_state, ledger))
        else:
            task_state = deepcopy(pivot_job['payload']['planning_intent']['task'])
            scope = dict(scope_id=failed['microtask_id'], failed_role=failed['role'], lineage_root=root, parent_floor=ledger['floor'],
                last_failed_model=ledger['last_model'], requirement_ids=failed['requirement_ids'],
                deliverables=failed['deliverables'], release_criteria=failed['release_criteria'])
        task_state.update(fracture_scope=scope, fracture_recommendation=pivot_result['output'])
        tier = max(min(10, ledger['floor'] + 1), scope.get('minimum_assembly_complexity', 1))
        plan_tags = task_state['assessment']['task_types'] if not failed else source_intent['task_types']
        if row:
            plan_job = self.store.get(row['plan_job_id'])
        else:
            candidates = select_pivot_candidates(captured.catalog, plan_tags, tier,
                                                last_failed_model=ledger['last_model'])
            if not candidates:
                return dict(status='CAPABILITY_HOLD')
            try:
                plan_job = self._submit(source, stage='FRACTURE_PLAN', task_state=task_state,
                    tier=tier, tags=plan_tags, candidates=candidates)
            except LineageBudgetHold as hold:
                return dict(status='FRACTURE_PLAN_BUDGET_HOLD', reason=hold.reason)
        if row is None:
            with self.journal._write() as conn:
                conn.execute('INSERT INTO planning428_fracture_plans VALUES(?,?,?,?,?,?,NULL,?,NULL)',
                    (root, number, task_id, source['job_id'], pivot_job['job_id'], plan_job['job_id'], 'WAITING_FOR_FRACTURE_PLAN'))
        result = PlanningGateway(self.journal, self.store).model_result(plan_job['job_id'])
        if result is None:
            return dict(status='FRACTURE_PLAN_HELD' if plan_job['status'] in ('FAILED', 'BLOCKED') else 'WAITING_FOR_FRACTURE_PLAN')
        plan = validate_fracture_plan(plan_job['payload'], result['output'])
        task_state = deepcopy(plan_job['payload']['planning_intent']['task'])
        scope = task_state['fracture_scope']
        plan_sha = digest(result)
        planner = captured.catalog['models'][result['profile_id']]
        review_tier = min(10, max(child['complexity'] for child in plan['children']) + 1)
        tags = sorted(set(tag for child in plan['children'] for tag in child['task_types']))
        candidates = [item for item in select_pivot_candidates(captured.catalog, tags, review_tier,
            last_failed_model=planner['family']) if item['family'] != scope['last_failed_model']]
        if not candidates:
            return dict(status='FRACTURE_REVIEW_CAPABILITY_HOLD')
        review_state = dict(task_state, fracture_plan=plan, fracture_plan_profile=result['profile_id'])
        try:
            review_job = self._submit(source, stage='FRACTURE_REVIEW', task_state=review_state,
                tier=review_tier, tags=tags, candidates=candidates, extra=dict(fracture_plan_sha256=plan_sha))
        except LineageBudgetHold as hold:
            return dict(status='FRACTURE_REVIEW_BUDGET_HOLD', reason=hold.reason)
        with self.journal._write() as conn:
            conn.execute('UPDATE planning428_fracture_plans SET review_job_id=?,status=? WHERE lineage_root=? AND boundary=?',
                         (review_job['job_id'], 'WAITING_FOR_FRACTURE_REVIEW', root, number))
        reviewed = PlanningGateway(self.journal, self.store).model_result(review_job['job_id'])
        if reviewed is None:
            return dict(status='FRACTURE_REVIEW_HELD' if review_job['status'] in ('FAILED', 'BLOCKED') else 'WAITING_FOR_FRACTURE_REVIEW')
        verdict = validate_fracture_review(review_job['payload'], reviewed['output'])
        if not verdict['accepted']:
            revision = task_state.get('fracture_revision', 0)
            if revision >= 9:
                return dict(status='FRACTURE_REVIEW_REVISION_LIMIT')
            revised = dict(task_state, fracture_revision=revision + 1,
                fracture_review_feedback=dict(plan_job_id=plan_job['job_id'], plan_sha256=plan_sha,
                    previous_plan=plan, review_job_id=review_job['job_id'], review_sha256=digest(reviewed),
                    findings=verdict['findings']))
            planning_tier = plan_job['payload']['planning_intent']['complexity']
            planning_tags = plan_job['payload']['planning_intent']['task_types']
            candidates = select_pivot_candidates(captured.catalog, planning_tags, planning_tier,
                                                last_failed_model=scope['last_failed_model'])
            try:
                replacement = self._submit(source, stage='FRACTURE_PLAN', task_state=revised,
                    tier=planning_tier, tags=planning_tags, candidates=candidates)
            except LineageBudgetHold as hold:
                return dict(status='FRACTURE_PLAN_BUDGET_HOLD', reason=hold.reason)
            with self.journal._write() as conn:
                conn.execute('UPDATE planning428_fracture_plans SET plan_job_id=?,review_job_id=NULL,status=? '
                    'WHERE lineage_root=? AND boundary=?',
                    (replacement['job_id'], 'WAITING_FOR_FRACTURE_PLAN', root, number))
            return dict(status='WAITING_FOR_FRACTURE_PLAN')
        reviewer = captured.catalog['models'][reviewed['profile_id']]
        prefix = 'fr428-' + digest(dict(root=root, boundary=number))[:16] + '-'
        names = {child['id']: prefix + str(index) for index, child in enumerate(plan['children'])}
        children = [dict(child, id=names[child['id']], depends_on=[names[d] for d in child['depends_on']])
                    for child in plan['children']]
        review = dict(reviewer_model=reviewer['family'], reviewer_tier=review_tier, effort=reviewer['effort'],
                      accepted=True, review_sha256=digest(reviewed))
        existing = captured.accepted_record(root, number)
        if existing is None:
            dossier = self.outcomes.dossier_store.get_dossier(root, number)
            self.outcomes.dossier_store.record_dossier(root, number, research_channels=dossier['research'],
                root_cause_synthesis=pivot_result['output']['root_cause_synthesis'], hypotheses=pivot_result['output']['hypotheses'])
            try:
                captured.execute_fracture(root, failed_scope=scope, children=children, review=review,
                                         dossier_boundary=number)
            except PivotHoldError as error:
                return dict(status=error.hold_status)
            existing = captured.accepted_record(root, number)
        if existing['graph']['review'] != review:
            raise ValueError('Registered fracture belongs to different review evidence')
        with self.journal._write() as conn:
            conn.execute('UPDATE planning428_fracture_plans SET status=?,fracture_id=? WHERE lineage_root=? AND boundary=?',
                         ('FRACTURE_READY_NEW_CAPTURE', existing['fracture_id'], root, number))
        if not failed:
            activate_promotion(self.journal, task_id, existing)
        return dict(status='FRACTURE_READY_NEW_CAPTURE', fracture_id=existing['fracture_id'])

    def promoted_record(self, task_id, state):
        binding = state.get('promoted_fracture')
        if not binding:
            raise ValueError('Task has no registered whole-task promotion')
        with self.journal._write() as conn:
            row = conn.execute('SELECT * FROM planning428_fracture_plans WHERE task_id=? AND lineage_root=? AND boundary=?',
                (task_id, binding['lineage_root'], binding['after_failures'])).fetchone()
        if row is None or row['fracture_id'] != binding['fracture_id'] or row['status'] != 'FRACTURE_READY_NEW_CAPTURE':
            raise ValueError('Whole-task graph lacks its committed promotion projection')
        source = self.store.get(row['source_job_id'])
        if source['payload'].get('microtask_node') or source['job_id'] != state['fracture_promotion']['source_job_id']:
            raise ValueError('Promoted graph belongs to a different original task scope')
        record = self.fracture_runtime.accepted_record(binding['lineage_root'], binding['after_failures'])
        if record is None or record['fracture_id'] != binding['fracture_id']:
            raise ValueError('Promoted graph lacks registered authority')
        return record

    def cancellation_targets(self, task_id):
        with self.journal._write() as conn:
            rows = conn.execute('SELECT plan_job_id,review_job_id FROM planning428_fracture_plans WHERE task_id=?', (task_id,))
            ids = [value for row in rows for value in row if value]
            ids += [row[0] for row in conn.execute('SELECT job_id FROM planning428_fracture_controls WHERE task_id=?', (task_id,))]
            return list(dict.fromkeys(ids))

    def records_for_task(self, task_id, generation):
        """Committed fractures only, scoped to their immutable original WBS generation."""
        with self.journal._write() as conn:
            rows = conn.execute("SELECT * FROM planning428_fracture_plans WHERE task_id=? "
                "AND status='FRACTURE_READY_NEW_CAPTURE' ORDER BY boundary,lineage_root", (task_id,)).fetchall()
        records = []
        for row in rows:
            source = self.store.get(row['source_job_id'])
            if source['payload']['planning_intent'].get('plan_generation_sha256') != generation:
                continue
            record = self.fracture_runtime.accepted_record(row['lineage_root'], row['boundary'])
            if record is None or record['fracture_id'] != row['fracture_id']:
                raise ValueError('Fracture task projection has no committed matching graph')
            records.append(dict(record, source_job=source))
        from .fracture_routes_428 import amend_records
        return amend_records(self, task_id, records)
