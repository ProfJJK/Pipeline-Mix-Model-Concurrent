"""4.2.8 planning contracts and durable quality-attempt accounting.

Reducer inputs are controller-validated records, never model-granted authority.
The owner approval receipt must be authenticated by the operator boundary before
calling ``approve_srs``. Research receipts must come from controller-run search
adapters. These functions validate binding and ordering; a digest alone does not
attest that a search, a model call or a human approval happened.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .task_routing import context_fits, digest, validate_task_tags


def _text(value, label, limit=16000):
    if not isinstance(value, str) or not value.strip() or '\x00' in value or len(value) > limit:
        raise ValueError(f'{label} requires bounded nonempty text')
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value):
        raise ValueError('Invalid literal identifier')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Evidence requires a SHA256 digest')
    return value


def _texts(value, label):
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise ValueError(f'{label} requires a bounded nonempty list')
    return [_text(item, label) for item in value]


def assessment(value):
    if not isinstance(value, dict) or set(value) != {'complexity', 'task_types', 'rationale'}:
        raise ValueError('Assessment requires complexity, task types and rationale')
    score = value['complexity']
    if type(score) is not int or not 1 <= score <= 10:
        raise ValueError('Complexity must be an integer from 1 to 10')
    return dict(complexity=score, task_types=validate_task_tags(value['task_types']),
                rationale=_text(value['rationale'], 'Assessment rationale'))


def new_task(task_id, objective):
    return dict(schema='cochem-task-workflow/4.2.8', task_id=_id(task_id),
        objective=_text(objective, 'Objective'), stage='SRS', revision=0,
        approval=None, review=None, research=None, history=[])


def _stage(state, *allowed):
    if state.get('schema') != 'cochem-task-workflow/4.2.8' or state.get('stage') not in allowed:
        raise ValueError('Operation is not eligible in the current workflow stage')


def accept_srs(state, document, *, planner_model, flash_context_limit):
    _stage(state, 'SRS', 'REVISING_SRS', 'OWNER_APPROVAL', 'RESEARCH', 'PLAN_REVIEW')
    fields = {'plan', 'architecture', 'srs', 'requirements', 'assessment', 'release_criteria',
              'srs_tokens', 'evidence_and_instruction_tokens', 'output_reserve_tokens'}
    if not isinstance(document, dict) or set(document) != fields:
        raise ValueError('SRS requires complete plan, architecture, requirements and token budget')
    for key in ('plan', 'architecture'):
        _text(document[key], key, 200000)
    classification = assessment(document['assessment'])
    _texts(document['release_criteria'], 'Release criteria')
    requirements = document['requirements']
    sections = document['srs']
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 200:
        raise ValueError('SRS requires one to 200 requirements')
    requirement_ids = set()
    for requirement in requirements:
        if not isinstance(requirement, dict) or set(requirement) != {'id', 'text'}:
            raise ValueError('Requirements require IDs and text')
        if _id(requirement['id']) in requirement_ids:
            raise ValueError('Duplicate requirement ID')
        requirement_ids.add(requirement['id'])
        _text(requirement['text'], 'Requirement')
    if not isinstance(sections, list) or not 1 <= len(sections) <= 200:
        raise ValueError('SRS requires bounded sections')
    covered, section_ids = set(), set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {'id', 'requirement_ids', 'text'}:
            raise ValueError('SRS sections require IDs, text and requirement links')
        if _id(section['id']) in section_ids:
            raise ValueError('Duplicate SRS section ID')
        section_ids.add(section['id'])
        _text(section['text'], 'SRS section', 200000)
        ids = _texts(section['requirement_ids'], 'Requirement links')
        if len(ids) != len(set(ids)) or set(ids) - requirement_ids:
            raise ValueError('Section links unknown or duplicate requirements')
        covered.update(ids)
    if covered != requirement_ids:
        raise ValueError('SRS must cover every requirement')
    # Model-supplied token estimates cannot grant the short-task fast path.
    # Count the complete UTF-8 document conservatively and reserve controller
    # instructions/output independently. Native context limits still require
    # acceptance; a missing bound always sends the task through review.
    for name in ('srs_tokens', 'evidence_and_instruction_tokens', 'output_reserve_tokens'):
        if type(document[name]) is not int or document[name] < 0:
            raise ValueError('Token estimates must be nonnegative integers')
    content_budget = max(document['srs_tokens'], len(json.dumps(document, ensure_ascii=False).encode('utf-8')))
    instruction_budget = max(document['evidence_and_instruction_tokens'], 4096 + len(state['objective'].encode('utf-8')))
    output_budget = max(document['output_reserve_tokens'], 4096)
    fits = context_fits(content_budget, instruction_budget, output_budget, flash_context_limit)
    result = deepcopy(state)
    sha = digest(document)
    if result.get('srs_sha256') != sha:
        if result.get('srs_sha256'):
            result['history'].append(dict(srs_sha256=result['srs_sha256'],
                assessment=result['assessment'], approval=result['approval'], review=result['review']))
        result.update(revision=state['revision'] + 1, approval=None, review=None, research=None)
    elif result.get('planner_model') != planner_model:
        result['review'] = None
    result.update(document=deepcopy(document), srs_sha256=sha, assessment=classification,
        planner_model=_id(planner_model), approval_required=classification['complexity'] >= 8,
        review_tier=min(10, classification['complexity'] + 1), fits_flash_context=fits,
        needs_wbs=classification['complexity'] >= 4 or len(classification['task_types']) > 1 or not fits)
    result['context_budget'] = dict(content=content_budget, instructions=instruction_budget, output=output_budget)
    result['stage'] = _next_plan_stage(result)
    return result


def _next_plan_stage(state):
    if state['approval_required'] and not state.get('approval'):
        return 'OWNER_APPROVAL'
    if state['assessment']['complexity'] >= 4 and not state.get('research'):
        return 'RESEARCH'
    if state['needs_wbs'] and not state.get('review'):
        return 'PLAN_REVIEW'
    return 'WBS' if state['needs_wbs'] else 'READY'


def approve_srs(state, expected_sha256, authenticated_owner_receipt_id):
    """Internal operation; the caller authenticates the human receipt, not an LLM."""
    _stage(state, 'OWNER_APPROVAL')
    if _sha(expected_sha256) != state['srs_sha256']:
        raise ValueError('Approval belongs to a different SRS revision')
    result = deepcopy(state)
    result['approval'] = dict(srs_sha256=expected_sha256,
                             receipt_id=_id(authenticated_owner_receipt_id))
    result['stage'] = _next_plan_stage(result)
    return result


def validate_research(research):
    if not isinstance(research, dict) or set(research) != {'internet', 'wiki_rag', 'papers'}:
        raise ValueError('Research must include internet, wiki RAG and papers')
    for kind, record in research.items():
        if not isinstance(record, dict) or set(record) != {'query', 'status', 'receipt_sha256', 'sources'}:
            raise ValueError('Research channel requires query, status, source and execution receipt')
        _text(record['query'], 'Research query', 2000)
        _sha(record['receipt_sha256'])
        if record['status'] not in ('found', 'no_results', 'unavailable'):
            raise ValueError('Unknown research disposition')
        sources = record['sources']
        if not isinstance(sources, list) or len(sources) > 30 or bool(sources) != (record['status'] == 'found'):
            raise ValueError('Research sources do not match search outcome')
        for source in sources:
            if not isinstance(source, dict) or set(source) != {'id', 'sha256'}:
                raise ValueError('Research source requires ID and content digest')
            _text(source['id'], 'Research source identifier', 2048)
            _sha(source['sha256'])
    return deepcopy(research)


def accept_research(state, research):
    _stage(state, 'RESEARCH', 'RESEARCH_HOLD')
    research = validate_research(research)
    result = deepcopy(state)
    result['research_attempt'] = research
    if any(record['status'] == 'unavailable' for record in research.values()):
        result['stage'] = 'RESEARCH_HOLD'
    else:
        result.update(research=dict(srs_sha256=state['srs_sha256'], channels=research), stage='PLAN_REVIEW')
    return result


def accept_review(state, *, reviewer_model, reviewer_tier, effort, accepted, review_sha256):
    _stage(state, 'PLAN_REVIEW')
    _id(reviewer_model)
    _sha(review_sha256)
    if (reviewer_model == state['planner_model'] or type(reviewer_tier) is not int
            or reviewer_tier != state['review_tier'] or type(accepted) is not bool):
        raise ValueError('Plan review requires a different model at the specified higher tier')
    maximum = 'high' if reviewer_model.startswith('gemini-') else 'max'
    if state['assessment']['complexity'] == 10 and effort != maximum:
        raise ValueError('Tier ten requires maximum-effort independent review')
    result = deepcopy(state)
    if not accepted:
        result.update(stage='REVISING_SRS', review=None)
    else:
        result.update(stage='WBS', review=dict(model=reviewer_model, tier=reviewer_tier,
            effort=effort, sha256=review_sha256, srs_sha256=state['srs_sha256']))
    return result


def _dag(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError('Work breakdown requires one to 200 nodes')
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or _id(row.get('id')) in by_id:
            raise ValueError('Duplicate work node')
        by_id[row['id']] = row
    remaining = set(by_id)
    ancestors = {}
    for row in rows:
        dependencies = row.get('depends_on')
        if (not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies)
                or len(dependencies) != len(set(dependencies)) or set(dependencies) - set(by_id)):
            raise ValueError('Unknown or duplicate dependency')
    while remaining:
        ready = [key for key in remaining if not set(by_id[key]['depends_on']) & remaining]
        if not ready:
            raise ValueError('Dependency cycle')
        for key in ready:
            dependencies = set(by_id[key]['depends_on'])
            ancestors[key] = dependencies | set().union(*(ancestors[x] for x in dependencies))
        remaining.difference_update(ready)
    return ancestors


def accept_wbs(state, rows):
    _stage(state, 'WBS')
    _dag(rows)
    sections = {x['id']: set(x['requirement_ids']) for x in state['document']['srs']}
    all_requirements = {x['id'] for x in state['document']['requirements']}
    covered = set()
    for row in rows:
        if set(row) != {'id', 'section_ids', 'requirement_ids', 'deliverables', 'audit_metrics', 'release_criteria', 'depends_on'}:
            raise ValueError('WBS requires full traceability and acceptance fields')
        section_ids = _texts(row['section_ids'], 'SRS section links')
        requirements = set(_texts(row['requirement_ids'], 'WBS requirement links'))
        if set(section_ids) - sections.keys() or requirements - set().union(*(sections[x] for x in section_ids)):
            raise ValueError('WBS links unknown sections or requirements')
        for field in ('deliverables', 'audit_metrics', 'release_criteria'):
            _texts(row[field], field)
        covered.update(requirements)
    if covered != all_requirements:
        raise ValueError('WBS omits SRS requirements')
    result = deepcopy(state)
    result.update(wbs=deepcopy(rows), wbs_sha256=digest(rows), stage='MICROTASKS')
    return result


def accept_microtasks(state, rows):
    _stage(state, 'MICROTASKS')
    ancestors = _dag(rows)
    wbs = {row['id']: row for row in state['wbs']}
    covered, implementations, assemblies, final_tests = set(), set(), set(), set()
    for row in rows:
        if set(row) != {'id', 'wbs_ids', 'role', 'complexity', 'task_types', 'deliverables',
                       'audit_metrics', 'release_criteria', 'depends_on', 'prompt'}:
            raise ValueError('Microtasks require prompts, assessments and acceptance fields')
        links = set(_texts(row['wbs_ids'], 'Microtask WBS links'))
        if links - wbs.keys():
            raise ValueError('Microtask links unknown WBS item')
        covered.update(links)
        assessment(dict(complexity=row['complexity'], task_types=row['task_types'], rationale=row['prompt']))
        for field in ('deliverables', 'audit_metrics', 'release_criteria'):
            _texts(row[field], field)
        if row['role'] == 'implementation':
            implementations.add(row['id'])
        elif row['role'] == 'assembly':
            assemblies.add(row['id'])
        elif row['role'] == 'final_test':
            final_tests.add(row['id'])
        elif row['role'] != 'orchestration':
            raise ValueError('Unknown microtask role')
    if covered != wbs.keys() or not implementations or not assemblies or not final_tests:
        raise ValueError('Microtasks must cover WBS and include implementation, assembly and final tests')
    if not any(implementations <= ancestors[x] for x in assemblies):
        raise ValueError('Assembly must depend on every implementation fragment')
    if not any(implementations | assemblies <= ancestors[x] for x in final_tests):
        raise ValueError('Final testing must follow every fragment and assembly')
    # A downstream WBS dependency must survive the microtask expansion.
    for row in rows:
        required = set().union(*(set(wbs[x]['depends_on']) for x in row['wbs_ids']))
        covered_ancestors = set().union(*(set(x['wbs_ids']) for x in rows if x['id'] in ancestors[row['id']]))
        if required - covered_ancestors:
            raise ValueError('Microtasks dropped a WBS dependency')
    result = deepcopy(state)
    result.update(microtasks=deepcopy(rows), microtasks_sha256=digest(rows),
        stage='MICROTASK_ASSESSMENT', efficient_microtasks=sum(
            row['complexity'] <= 5 and len(row['task_types']) == 1 for row in rows))
    return result


def approve_microtask(state, microtask_id, expected_microtasks_sha256, authenticated_owner_receipt_id):
    """Record a verified human-owner approval for a newly high-tier (8..10) reassessed microtask."""
    _stage(state, 'MICROTASKS_READY')
    _id(microtask_id)
    _id(authenticated_owner_receipt_id)
    if _sha(expected_microtasks_sha256) != state.get('microtasks_sha256'):
        raise ValueError('Microtask approval belongs to a different microtask revision')
    result = deepcopy(state)
    matched = False
    for row in result.get('microtasks', []):
        if row['id'] == microtask_id:
            if not 8 <= int(row['complexity']) <= 10:
                raise ValueError('Only complexity 8..10 microtasks require child owner approval')
            row['owner_approval'] = dict(
                receipt_id=authenticated_owner_receipt_id,
                microtasks_sha256=expected_microtasks_sha256,
            )
            matched = True
            break
    if not matched:
        raise ValueError('Unknown microtask ID')
    return result


def compile_reassessed_microtask_plan(state):
    """Compile a validated, requirement-linked DAG of reassessed microtask descriptors (`P428-12`)."""
    _stage(state, 'MICROTASKS_READY')
    rows = state.get('microtasks')
    wbs_rows = state.get('wbs')
    if not isinstance(rows, list) or not isinstance(wbs_rows, list):
        raise ValueError('Task state is missing WBS or reassessed microtasks')
    ancestors = _dag(rows)
    wbs_by_id = {row['id']: row for row in wbs_rows}
    all_srs_reqs = {req['id'] for req in state['document']['requirements']}
    covered_reqs = set()

    compiled = []
    for row in rows:
        if 'assessment' not in row:
            raise ValueError(f"Microtask {row.get('id')} is missing individual reassessment")
        check = assessment(row['assessment'])
        if row.get('complexity') != check['complexity'] or row.get('task_types') != check['task_types']:
            raise ValueError(f"Microtask {row.get('id')} classification does not match its assessment")
        wbs_ids = _texts(row['wbs_ids'], 'Microtask WBS links')
        if set(wbs_ids) - wbs_by_id.keys():
            raise ValueError('Microtask links unknown WBS item')
        req_ids = sorted(set().union(*(set(wbs_by_id[w]['requirement_ids']) for w in wbs_ids)))
        sec_ids = sorted(set().union(*(set(wbs_by_id[w]['section_ids']) for w in wbs_ids)))
        if not req_ids or set(req_ids) - all_srs_reqs:
            raise ValueError(f"Microtask {row['id']} lacks valid SRS requirement links")
        covered_reqs.update(req_ids)
        for field in ('deliverables', 'audit_metrics', 'release_criteria'):
            _texts(row[field], field)

        needs_child_approval = False
        if 8 <= check['complexity'] <= 10:
            child_app = row.get('owner_approval')
            if not (isinstance(child_app, dict) and child_app.get('receipt_id')):
                needs_child_approval = True

        compiled.append(
            dict(
                microtask_id=row['id'],
                parent_task_id=state['task_id'],
                lineage_kind='WBS_CHILD',
                attempt_lineage_id=f"{state['task_id']}::mt::{row['id']}",
                role=row['role'],
                complexity=check['complexity'],
                task_types=list(check['task_types']),
                assessment=deepcopy(check),
                wbs_ids=list(wbs_ids),
                section_ids=sec_ids,
                requirement_ids=req_ids,
                deliverables=list(row['deliverables']),
                audit_metrics=list(row['audit_metrics']),
                release_criteria=list(row['release_criteria']),
                depends_on=list(row['depends_on']),
                ancestors=sorted(ancestors[row['id']]),
                prompt=_text(row['prompt'], 'Microtask prompt', 200000),
                needs_owner_approval=needs_child_approval,
                owner_approval=deepcopy(row.get('owner_approval')),
            )
        )

    if covered_reqs != all_srs_reqs:
        raise ValueError('Compiled microtask graph does not cover every SRS requirement')
    return compiled


class AttemptLedger:
    """Serial, fenced quality cycles shared by pivot/fracture descendants.

    Interrupted ACTIVE records hold until the controller proves cleanup. This
    ledger never infers death from elapsed wall time or resets a spent budget.
    Normal WBS siblings get independent roots; only a failure fracture shares
    its parent's lineage budget. It is not an additional execution pool.
    """
    def __init__(self, path):
        self.path = Path(path)
        if str(path) == ':memory:':
            raise ValueError('Quality budget requires a durable database')
        with self._write() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS task428_lineages(
                  root TEXT PRIMARY KEY, state_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task428_members(
                  task_id TEXT PRIMARY KEY, root TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task428_attempts(
                  lease TEXT PRIMARY KEY, root TEXT NOT NULL, task_id TEXT NOT NULL,
                  model TEXT NOT NULL, result_json TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS task428_one_active
                  ON task428_attempts(root) WHERE result_json IS NULL;
            ''')

    @contextmanager
    def _write(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _read(conn, task_id):
        row = conn.execute('SELECT l.state_json FROM task428_lineages l '
            'JOIN task428_members m ON l.root=m.root WHERE m.task_id=?', (task_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown task lineage')
        return json.loads(row[0])

    @staticmethod
    def _save(conn, state):
        conn.execute('UPDATE task428_lineages SET state_json=? WHERE root=?',
                     (json.dumps(state, sort_keys=True, allow_nan=False), state['root']))

    def create(self, root, complexity=1):
        _id(root)
        assessment(dict(complexity=complexity, task_types=['GEN-DEFAULT'], rationale='Initial lineage'))
        with self._write() as conn:
            if conn.execute('SELECT 1 FROM task428_members WHERE task_id=?', (root,)).fetchone():
                raise ValueError('Lineage already exists; budgets cannot be reset')
            state = dict(root=root, failures=0, pivots=[], stage='READY', floor=complexity,
                         next_model=None, last_model=None, research_due=False, decisions=[])
            conn.execute('INSERT INTO task428_lineages VALUES(?,?)', (root, json.dumps(state)))
            conn.execute('INSERT INTO task428_members VALUES(?,?)', (root, root))
        return state

    def status(self, task_id):
        with self._write() as conn:
            return self._read(conn, task_id)

    def start(self, root, task_id, model):
        _id(model)
        with self._write() as conn:
            state = self._read(conn, task_id)
            if (state['root'] != root or state['stage'] != 'READY' or state['failures'] >= 30
                    or state['next_model'] not in (None, model)):
                raise ValueError('Lineage is held, locked or requires its pivot model')
            lease = uuid.uuid4().hex
            try:
                conn.execute('INSERT INTO task428_attempts VALUES(?,?,?,?,NULL)', (lease, root, task_id, model))
            except sqlite3.IntegrityError as exc:
                raise ValueError('Lineage already has an active quality cycle') from exc
            return lease

    def finish(self, lease, outcome, evidence_sha256):
        _sha(evidence_sha256)
        if outcome not in ('quality_failure', 'availability', 'success'):
            raise ValueError('Unknown quality-cycle outcome')
        with self._write() as conn:
            attempt = conn.execute('SELECT * FROM task428_attempts WHERE lease=?', (lease,)).fetchone()
            if attempt is None:
                raise ValueError('Unknown attempt fence')
            if attempt['result_json'] is not None:
                old = json.loads(attempt['result_json'])
                if old['outcome'] != outcome or old['evidence_sha256'] != evidence_sha256:
                    raise ValueError('Completed attempt evidence is immutable')
                return old['state']
            state = self._read(conn, attempt['task_id'])
            if outcome == 'quality_failure':
                state['failures'] += 1
                state['last_model'] = attempt['model']
                state['next_model'] = None
                if state['failures'] == 30:
                    state.update(stage='LOCKED', research_due=True)
                elif state['failures'] % 10 == 0:
                    state.update(stage='PIVOT_RESEARCH', research_due=True)
            elif outcome == 'success':
                state['next_model'] = None
            result = dict(outcome=outcome, evidence_sha256=evidence_sha256, state=state)
            conn.execute('UPDATE task428_attempts SET result_json=? WHERE lease=? AND result_json IS NULL',
                         (json.dumps(result, sort_keys=True), lease))
            self._save(conn, state)
            return state

    def pivot(self, root, research, proposal, evidence_sha256):
        research = validate_research(research)
        _sha(evidence_sha256)
        if any(x['status'] == 'unavailable' for x in research.values()):
            raise ValueError('Pivot research is incomplete')
        if not isinstance(proposal, dict) or set(proposal) != {
                'strategy', 'task_types', 'complexity', 'rationale', 'next_model', 'children'}:
            raise ValueError('Pivot requires reassessment and an explicit strategy')
        assessment({key: proposal[key] for key in ('complexity', 'task_types', 'rationale')})
        _id(proposal['next_model'])
        children = proposal['children']
        if (proposal['strategy'] not in ('pivot', 'fracture') or not isinstance(children, list)
                or len(children) > 200 or len(set(children)) != len(children)
                or bool(children) != (proposal['strategy'] == 'fracture')):
            raise ValueError('Invalid pivot/fracture membership')
        for child in children:
            _id(child)
        with self._write() as conn:
            state = self._read(conn, root)
            if state['root'] != root or state['stage'] not in ('PIVOT_RESEARCH', 'LOCKED') or not state['research_due']:
                raise ValueError('No pivot is due')
            if proposal['next_model'] == state['last_model']:
                raise ValueError('A quality pivot must use a different underlying model')
            state['pivots'].append(dict(after_failures=state['failures'], research=research,
                proposal=deepcopy(proposal), evidence_sha256=evidence_sha256))
            state['research_due'] = False
            if state['stage'] != 'LOCKED':
                for child in children:
                    if conn.execute('SELECT 1 FROM task428_members WHERE task_id=?', (child,)).fetchone():
                        raise ValueError('Fracture child already belongs to a lineage')
                    conn.execute('INSERT INTO task428_members VALUES(?,?)', (child, root))
                state.update(stage='READY', next_model=proposal['next_model'],
                    floor=max(proposal['complexity'], min(10, state['floor'] + 1)))
            self._save(conn, state)
            return state

    def decision_packets(self):
        """Read-only projection for the next status request; never unlocks work."""
        with self._write() as conn:
            locked = [json.loads(row[0]) for row in conn.execute('SELECT state_json FROM task428_lineages')]
            return [dict(root=x['root'], failures=x['failures'], stage='LOCKED',
                research_due=x['research_due'], pivots=x['pivots'],
                options=[dict(action='revise_scope', pros='Reduce the unresolved problem',
                              cons='Changes the requested scope', risks='May omit required behavior'),
                         dict(action='defer', pros='Preserve evidence and spent quota',
                              cons='Task remains unfinished', risks='Dependent work remains blocked')])
                for x in locked if x['stage'] == 'LOCKED']
