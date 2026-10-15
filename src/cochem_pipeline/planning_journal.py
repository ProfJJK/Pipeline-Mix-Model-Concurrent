"""Durable 4.2.8 planning coordinator, with trusted controller evidence ports.

This creates planning intents, not execution leases or additional worker slots.
The existing Chapter 06 scheduler must reserve a native target before submitting
an intent. Model/search/owner results are loaded through distinct controller
ports; generated content cannot create approval or research authority.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from . import workflow_428 as workflow
from .task_routing import digest, select_candidates, select_reviewers, five_model_options


class PlanningJournal:
    def __init__(self, path, catalog, *, model_result=None, search_result=None,
                 owner_receipt=None, flash_context_limit=None):
        if str(path) == ':memory:':
            raise ValueError('Planning requires a durable journal')
        self.path = Path(path)
        self.catalog = deepcopy(catalog)
        if catalog.get('schema') != 'cochem-task-routing/1':
            raise ValueError('Planning requires a versioned task catalog')
        self.model_result, self.search_result, self.owner_receipt = model_result, search_result, owner_receipt
        if flash_context_limit is not None:
            if type(flash_context_limit) is not int or not 1 <= flash_context_limit <= 10**9:
                raise ValueError('Invalid verified Flash prompt limit')
        self.flash_context_limit = flash_context_limit
        with self._write() as conn:
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS planning428_tasks(
                task_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, catalog_json TEXT NOT NULL,
                version INTEGER NOT NULL, flash_context_limit INTEGER);
              CREATE TABLE IF NOT EXISTS planning428_events(
                event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, before_version INTEGER NOT NULL,
                input_sha256 TEXT NOT NULL, result_json TEXT NOT NULL);
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
        row = conn.execute('SELECT * FROM planning428_tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown planning task')
        return dict(row)

    def has_task(self, task_id) -> bool:
        try:
            workflow._id(task_id)
        except ValueError:
            return False
        with self._write() as conn:
            return conn.execute('SELECT 1 FROM planning428_tasks WHERE task_id=?', (task_id,)).fetchone() is not None

    def create(self, task_id, objective, *, project_id=None, requested_requirements=None):
        state = workflow.new_task(task_id, objective)
        requirements = [] if requested_requirements is None else requested_requirements
        if (not isinstance(requirements, list) or len(requirements) > 200
                or any(not isinstance(x, str) or not x.strip() or '\x00' in x for x in requirements)
                or len(set(requirements)) != len(requirements) or sum(len(x) for x in requirements) > 16000):
            raise ValueError('Requested requirements must be unique bounded nonempty strings')
        if requirements:
            state['requested_requirements'] = deepcopy(requirements)
        if project_id is not None:
            state['project_id'] = workflow._id(project_id)
        with self._write() as conn:
            existing = conn.execute('SELECT 1 FROM planning428_tasks WHERE task_id=?', (task_id,)).fetchone()
            if existing:
                old = self._read(conn, task_id)
                old_state = json.loads(old['state_json'])
                if (old_state['objective'] != objective or old_state.get('project_id') != project_id
                        or old_state.get('requested_requirements', []) != requirements):
                    raise ValueError('Task ID belongs to another objective or project')
                return self._projection(old)
            conn.execute('INSERT INTO planning428_tasks VALUES(?,?,?,?,?)',
                (task_id, json.dumps(state), json.dumps(self.catalog), 0, self.flash_context_limit))
            return self._projection(self._read(conn, task_id))

    def cancel(self, task_id):
        workflow._id(task_id)
        with self._write() as conn:
            row = self._read(conn, task_id)
            state = json.loads(row['state_json'])
            if state.get('stage') == 'COMPLETED':
                raise ValueError('Completed task cannot be cancelled')
            state['stage'] = 'CANCELLED'
            conn.execute('UPDATE planning428_tasks SET state_json=?,version=version+1 WHERE task_id=?',
                         (json.dumps(state, sort_keys=True, allow_nan=False), task_id))
            return self._projection(self._read(conn, task_id))

    @staticmethod
    def _projection(row):
        state = json.loads(row['state_json'])
        state.update(journal_version=row['version'], captured_catalog_sha256=digest(json.loads(row['catalog_json'])))
        return state

    def status(self, task_id):
        with self._write() as conn:
            return self._projection(self._read(conn, task_id))

    def intent(self, task_id):
        with self._write() as conn:
            row = self._read(conn, task_id)
            return self._intent(row)

    @staticmethod
    def _intent(row):
        state = json.loads(row['state_json'])
        catalog = json.loads(row['catalog_json'])
        stage = state['stage']
        request = dict(schema='cochem-planning-intent/4.2.8', task_id=state['task_id'],
            version=row['version'], stage=stage, state_sha256=digest(state),
            catalog_sha256=digest(catalog), srs_sha256=state.get('srs_sha256'),
            execution_authorized=False)
        if stage == 'OWNER_APPROVAL':
            return request | dict(action='owner_review', document=state['document'])
        if stage in ('RESEARCH', 'RESEARCH_HOLD'):
            return request | dict(action='controller_research', channels=['internet','wiki_rag','papers'],
                                  query=state['objective'][:2000])
        if stage in ('READY', 'MICROTASKS_READY'):
            return request | dict(action='jobboard_submission', task=state)
        if stage not in ('SRS', 'REVISING_SRS', 'PLAN_REVIEW', 'WBS', 'MICROTASKS', 'MICROTASK_ASSESSMENT'):
            return request | dict(action='hold')
        # Bootstrap planning is a bounded tier-4 assessment, not a final claim
        # that the task itself is tier 4. Its output determines the actual gates.
        classification = state.get('assessment', dict(complexity=4, task_types=['GEN-DEFAULT']))
        tier, tags = classification['complexity'], classification['task_types']
        if stage == 'PLAN_REVIEW':
            producer = state['planner_profile']
            candidates = select_reviewers(catalog, tags, tier, producer)
            tier = min(10, tier + 1)
        else:
            options = five_model_options(catalog, tags, tier)
            candidates = [option['model_id'] for option in options if option['meets_floor']]
        return request | dict(action='model_stage' if candidates else 'capability_hold',
            complexity=tier, task_types=tags, candidate_profiles=candidates, task=state,
            prompt_rule='Return the required planning artifact only; do not execute, delegate or grant approval.')

    @staticmethod
    def _load(port, key, label):
        if port is None:
            raise ValueError(label + ' controller evidence port is not configured')
        workflow._id(key)
        result = port(key)
        if not isinstance(result, dict):
            raise ValueError(label + ' evidence is unavailable')
        return deepcopy(result)

    def apply_model_result(self, task_id, expected_version, job_id):
        # Read committed execution evidence outside the journal write lock.
        # These fields must come from the scheduler DB, never model JSON.
        result = self._load(self.model_result, job_id, 'Model')
        if (set(result) != {'job_id','intent_sha256','profile_id','status','cleanup_verified','output'}
                or result['job_id'] != job_id or result['status'] != 'COMPLETED'
                or result['cleanup_verified'] is not True or not isinstance(result['output'], dict)):
            raise ValueError('Model result lacks completed, cleaned-up execution evidence')
        def transition(row):
            state, catalog = json.loads(row['state_json']), json.loads(row['catalog_json'])
            intent = self._intent(row)
            if (intent['action'] != 'model_stage' or result['intent_sha256'] != digest(intent)
                    or result['profile_id'] not in intent['candidate_profiles']):
                raise ValueError('Execution does not match this exact planning intent and candidate')
            model = catalog['models'][result['profile_id']]
            output, stage = result['output'], state['stage']
            if stage in ('SRS','REVISING_SRS'):
                updated = workflow.accept_srs(state, output, planner_model=model['family'],
                                              flash_context_limit=row['flash_context_limit'])
                updated['planner_profile'] = result['profile_id']
            elif stage == 'PLAN_REVIEW':
                if set(output) != {'accepted','findings','suggestions','clarifications'}:
                    raise ValueError('Review requires disposition, findings, suggestions and clarifications')
                for key in ('findings','suggestions','clarifications'):
                    if not isinstance(output[key], list) or len(output[key]) > 100:
                        raise ValueError('Review statements must be bounded arrays')
                    for text in output[key]:
                        workflow._text(text, 'Review statement')
                updated = workflow.accept_review(state, reviewer_model=model['family'],
                    reviewer_tier=intent['complexity'], effort=model['effort'],
                    accepted=output['accepted'], review_sha256=digest(output))
                updated['review_document'] = output
            elif stage == 'WBS':
                if set(output) != {'wbs'}:
                    raise ValueError('Expected WBS artifact')
                updated = workflow.accept_wbs(state, output['wbs'])
            elif stage == 'MICROTASKS':
                if set(output) != {'microtasks'}:
                    raise ValueError('Expected microtask artifact')
                updated = workflow.accept_microtasks(state, output['microtasks'])
            else:
                updated = self._accept_micro_assessments(state, output)
            updated.setdefault('accepted_planning_jobs', []).append(dict(job_id=job_id,
                profile_id=result['profile_id'], result_sha256=digest(result)))
            return updated
        return self._transition(task_id, expected_version, 'model.'+job_id, result, transition)

    @staticmethod
    def _accept_micro_assessments(state, output):
        if set(output) != {'assessments'} or not isinstance(output['assessments'], list):
            raise ValueError('Every microtask requires a fresh individual assessment')
        expected = {row['id'] for row in state['microtasks']}
        values = {}
        for row in output['assessments']:
            if not isinstance(row, dict) or set(row) != {'id','complexity','task_types','rationale'}:
                raise ValueError('Invalid microtask reassessment')
            if row['id'] not in expected or row['id'] in values:
                raise ValueError('Unknown or duplicate microtask assessment')
            values[row['id']] = workflow.assessment({k: row[k] for k in ('complexity','task_types','rationale')})
        if set(values) != expected:
            raise ValueError('Microtask reassessment omits a task')
        updated = deepcopy(state)
        for row in updated['microtasks']:
            row.update(assessment=values[row['id']], complexity=values[row['id']]['complexity'],
                       task_types=values[row['id']]['task_types'])
        updated.update(stage='MICROTASKS_READY', microtasks_sha256=digest(updated['microtasks']))
        return updated

    def apply_research(self, task_id, expected_version, research_id):
        result = self._load(self.search_result, research_id, 'Search')
        def transition(row):
            if (not {'intent_sha256', 'channels'} <= set(result)
                    or set(result) - {'intent_sha256', 'channels', 'excerpts'}
                    or result['intent_sha256'] != digest(self._intent(row))):
                raise ValueError('Search receipts belong to a different planning revision')
            excerpts = None
            if 'excerpts' in result:
                from .research_evidence_428 import validate_research_excerpts
                excerpts = validate_research_excerpts(result['channels'], result['excerpts'])
            updated = workflow.accept_research(json.loads(row['state_json']), result['channels'])
            if excerpts is not None and updated.get('stage') == 'PLAN_REVIEW':
                updated['research_excerpts'] = excerpts
            return updated
        return self._transition(task_id, expected_version, 'research.'+research_id, result, transition)

    def apply_owner_approval(self, task_id, expected_version, receipt_id):
        result = self._load(self.owner_receipt, receipt_id, 'Owner')
        def transition(row):
            state = json.loads(row['state_json'])
            from .owner_approval_428 import VALID_OWNER_DECISIONS, apply_owner_decision_to_state
            legacy_keys = {'task_id', 'srs_sha256', 'decision', 'actor_kind'}
            broker_keys = {
                'receipt_id', 'request_id', 'task_id', 'revision',
                'objective_sha256', 'srs_sha256', 'decision', 'notes',
                'actor_kind', 'hmac_sha256', 'broker_verified',
            }
            if set(result) not in (legacy_keys, broker_keys):
                raise ValueError('Only an authenticated human-owner approval is accepted')
            if (result['task_id'] != task_id
                    or result['actor_kind'] != 'human_owner'
                    or result['decision'] not in VALID_OWNER_DECISIONS):
                raise ValueError('Only an authenticated human-owner approval is accepted')
            if set(result) == broker_keys:
                if (result['receipt_id'] != receipt_id
                        or result['broker_verified'] is not True
                        or result['revision'] != state.get('revision')):
                    raise ValueError('Owner approval receipt failed broker or revision verification')
            return apply_owner_decision_to_state(
                state,
                expected_srs_sha256=result['srs_sha256'],
                receipt_id=receipt_id,
                decision=result['decision'],
                notes=result.get('notes', ''),
                objective_sha256=result.get('objective_sha256'),
            )
        return self._transition(task_id, expected_version, 'owner.'+receipt_id, result, transition)

    def _transition(self, task_id, version, event_id, evidence, reduce):
        if type(version) is not int or version < 0:
            raise ValueError('Invalid planning version')
        with self._write() as conn:
            old_event = conn.execute('SELECT * FROM planning428_events WHERE event_id=?', (event_id,)).fetchone()
            if old_event:
                if (old_event['task_id'] != task_id or old_event['before_version'] != version
                        or old_event['input_sha256'] != digest(evidence)):
                    raise ValueError('Planning evidence cannot be rebound or rewritten')
                return json.loads(old_event['result_json'])
            row = self._read(conn, task_id)
            if row['version'] != version:
                raise ValueError('Stale planning completion or approval')
            state = reduce(row)
            conn.execute('UPDATE planning428_tasks SET state_json=?,version=version+1 WHERE task_id=? AND version=?',
                         (json.dumps(state, sort_keys=True, allow_nan=False), task_id, version))
            result = self._projection(self._read(conn, task_id))
            conn.execute('INSERT INTO planning428_events VALUES(?,?,?,?,?)',
                (event_id, task_id, version, digest(evidence), json.dumps(result, sort_keys=True)))
            return result
