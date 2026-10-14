"""Bounded planning progression on the existing board, with no native executor.

The controller imports only committed, cleaned-up board results. Research and
human approval remain separate trusted evidence ports. Neither an HTTP caller
nor a planning model can manufacture those receipts. Execution materialization
is a separate consumer; READY here means the plan, not the deliverable, is ready.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
import time
import uuid

from .planning_gateway import PlanningGateway
from .planning_journal import PlanningJournal
from .task_routing import digest
from .workflow_428 import _id, _sha


@dataclass(frozen=True)
class PlanningConfig:
    catalog_file: Path
    catalog_sha256: str
    flash_context_limit: int | None = None

    @classmethod
    def from_dict(cls, value):
        if value is None:
            return None
        if (not isinstance(value, dict) or set(value) - {'catalog_file', 'catalog_sha256', 'flash_context_limit'}
                or not isinstance(value.get('catalog_file'), str) or '\x00' in value['catalog_file']):
            raise ValueError('Task planning requires a pinned protected catalog')
        path = Path(value['catalog_file'])
        if not path.is_absolute():
            raise ValueError('Task planning catalog must be an absolute protected path')
        sha = _sha(value.get('catalog_sha256'))
        limit = value.get('flash_context_limit')
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 10**9):
            raise ValueError('Invalid accepted Flash context limit')
        return cls(path, sha, limit)

    def read_catalog(self):
        # Called only at privileged Runtime construction. Decode the exact
        # bounded bytes whose digest was reviewed by the owner installer.
        from .windows import validate_code_path
        from .routing import _strict_json
        validate_code_path(self.catalog_file)
        with self.catalog_file.open('rb') as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if not 1 <= len(raw) <= 4 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != self.catalog_sha256:
            raise ValueError('Protected task catalog differs from its installation pin')
        catalog = _strict_json(raw.decode('utf-8'))
        if (not isinstance(catalog, dict) or catalog.get('schema') != 'cochem-task-routing/1'
                or catalog.get('host_accepted') is not True):
            raise ValueError('Task planning requires a host-accepted catalog; a research candidate cannot activate it')
        return catalog


class PlanningController:
    def __init__(
        self,
        journal,
        store,
        *,
        clock=time.time,
        research_runtime=None,
        execution_runtime=None,
        release_runtime=None,
    ):
        self.journal, self.store, self.clock = journal, store, clock
        self.research_runtime = research_runtime
        self.execution_runtime = execution_runtime
        self.release_runtime = release_runtime
        self.gateway = PlanningGateway(journal, store)
        self.journal.model_result = self.gateway.model_result
        if research_runtime is not None and self.journal.search_result is None:
            self.journal.search_result = research_runtime.evidence_store.load_for_journal
        self._lock = threading.Lock()
        with journal._write() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS planning428_progress(
                    task_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                    status TEXT NOT NULL, job_id TEXT, research_id TEXT,
                    error_type TEXT, checked_at REAL NOT NULL, next_check_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS planning428_cursor(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), task_id TEXT NOT NULL);
            ''')

    @classmethod
    def from_runtime(cls, runtime):
        spec = runtime.config.task_planning
        journal = PlanningJournal(runtime.config.private_root / 'planning428.db', spec.read_catalog(),
                                  flash_context_limit=spec.flash_context_limit)
        from .research_evidence_428 import ResearchEvidenceStore
        from .research_runtime_428 import ResearchRuntime
        from .research_search_428 import ResearchSearchClient
        from .task_execution_428 import SimpleTaskExecutionRuntime
        from .task_release_428 import TaskReleaseRuntime
        ev_store = ResearchEvidenceStore(runtime.config.private_root / 'research428.db')
        res_runtime = ResearchRuntime(
            ev_store,
            ResearchSearchClient(),
            knowledge_service=getattr(runtime, 'knowledge', None),
            knowledge_authority=getattr(runtime, 'knowledge_authority', None),
        )
        exec_runtime = SimpleTaskExecutionRuntime(journal, runtime.store)
        rel_runtime = TaskReleaseRuntime(journal, runtime.store)
        return cls(
            journal,
            runtime.store,
            research_runtime=res_runtime,
            execution_runtime=exec_runtime,
            release_runtime=rel_runtime,
        )

    def has_task(self, task_id) -> bool:
        return self.journal.has_task(task_id)

    def submit(self, objective, task_id=None, *, project_id=None):
        # No catalog, tier, approval, profile or dispatch arguments are accepted.
        task_id = _id(task_id if task_id is not None else 'task428-' + uuid.uuid4().hex)
        self.journal.create(task_id, objective, project_id=project_id)
        return self.task_status(task_id)

    def cancel(self, task_id):
        _id(task_id)
        current = self.task_status(task_id)
        job_id = (current.get('controller') or {}).get('job_id')
        state = self.journal.cancel(task_id)
        self._record(task_id, state['journal_version'], 'CANCELLED', job_id=job_id, delay=3600)
        return self.task_status(task_id)

    def task_status(self, task_id):
        _id(task_id)
        with self.journal._write() as conn:
            task = self.journal._projection(self.journal._read(conn, task_id))
            row = conn.execute('SELECT * FROM planning428_progress WHERE task_id=?', (task_id,)).fetchone()
            progress = dict(row) if row else {'status': 'NOT_YET_POLLED', 'version': task['journal_version']}
        completed = task.get('stage') == 'COMPLETED'
        result = dict(task=task, controller=progress, deliverable_completed=completed)
        if self.execution_runtime is not None and hasattr(self.execution_runtime, 'get_artifact'):
            art = self.execution_runtime.get_artifact(task_id)
            if art is not None:
                result['execution'] = art
        if self.release_runtime is not None and hasattr(self.release_runtime, 'get_release'):
            rel = self.release_runtime.get_release(task_id)
            if rel is not None:
                result['release'] = rel
        return result

    def status(self):
        with self.journal._write() as conn:
            total = conn.execute('SELECT count(*) FROM planning428_tasks').fetchone()[0]
            counts = dict(conn.execute('SELECT status,count(*) FROM planning428_progress GROUP BY status').fetchall())
        mat_state = 'CONNECTED' if (self.execution_runtime is not None or self.release_runtime is not None) else 'NOT_CONNECTED'
        return dict(status='ENABLED', tasks=total, states=counts, execution_materialization=mat_state)

    def _record(self, task_id, version, status, *, delay=1, job_id=None, research_id=None, error_type=None):
        now = self.clock()
        with self.journal._write() as conn:
            conn.execute('INSERT INTO planning428_progress VALUES(?,?,?,?,?,?,?,?) '
                'ON CONFLICT(task_id) DO UPDATE SET version=excluded.version,status=excluded.status,'
                'job_id=excluded.job_id,research_id=excluded.research_id,error_type=excluded.error_type,'
                'checked_at=excluded.checked_at,next_check_at=excluded.next_check_at',
                (task_id, version, status, job_id, research_id, error_type, now, now + delay))

    def _step_task(self, task_id):
        intent = self.journal.intent(task_id)
        version, action = intent['version'], intent['action']
        if action == 'model_stage':
            job = self.gateway.submit(task_id)
            if job['status'] == 'COMPLETED':
                if self.gateway.model_result(job['job_id']) is None:
                    self._record(task_id, version, 'WAITING_FOR_NATIVE_CLEANUP', job_id=job['job_id'])
                else:
                    self.journal.apply_model_result(task_id, version, job['job_id'])
                    self._record(task_id, version, 'PLANNING_RESULT_IMPORTED', job_id=job['job_id'], delay=0)
            elif job['status'] in ('FAILED', 'BLOCKED'):
                # A failed board job is never resubmitted as a fresh attempt.
                self._record(task_id, version, 'PLANNING_JOB_HELD', job_id=job['job_id'], delay=60)
            else:
                self._record(task_id, version, 'WAITING_FOR_BOARD', job_id=job['job_id'])
        elif action == 'controller_research':
            research_id = 'research428-' + digest(intent)[:40]
            # The collector writes a durable receipt keyed by this intent. A
            # poll never performs network I/O on the scheduler thread.
            if self.research_runtime is not None:
                self.research_runtime.enqueue(intent)
            port = self.journal.search_result
            result = port(research_id) if port is not None else None
            if result is None:
                delay = self.research_runtime.backoff_delay(research_id, default=30) if self.research_runtime is not None else 30
                self._record(task_id, version, 'WAITING_FOR_RESEARCH', research_id=research_id, delay=delay)
            else:
                self.journal.apply_research(task_id, version, research_id)
                self._record(task_id, version, 'RESEARCH_RESULT_IMPORTED', research_id=research_id, delay=0)
        elif action == 'jobboard_submission' and intent.get('stage') == 'READY' and self.execution_runtime is not None:
            res = self.execution_runtime.step_ready_task(task_id)
            self._record(task_id, version, res['status'], job_id=res.get('job_id'), delay=res.get('delay', 1))
        elif action == 'jobboard_submission' and intent.get('stage') == 'MICROTASKS_READY' and self.release_runtime is not None:
            res = self.release_runtime.step_microtask_task(task_id)
            self._record(task_id, version, res['status'], job_id=res.get('job_id'), delay=res.get('delay', 1))
        elif intent.get('stage') == 'COMPLETED':
            self._record(task_id, version, 'EXECUTION_COMPLETED', delay=3600)
        else:
            status = {'owner_review': 'WAITING_FOR_OWNER_APPROVAL',
                      'jobboard_submission': 'PLAN_READY_EXECUTION_PENDING',
                      'capability_hold': 'CAPABILITY_HOLD'}.get(action, 'PLANNING_HELD')
            self._record(task_id, version, status, delay=30)

    def step(self, limit=8):
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('Planning poll must be bounded to 1..32 tasks')
        if not self._lock.acquire(blocking=False):
            return 0
        try:
            with self.journal._write() as conn:
                row = conn.execute('SELECT task_id FROM planning428_cursor WHERE singleton=1').fetchone()
                cursor = row[0] if row else ''
                # Version changes bypass an earlier hold's polling delay. Keyset
                # rotation survives restart and prevents held tasks starving new ones.
                ids = [r[0] for r in conn.execute(
                    'SELECT t.task_id FROM planning428_tasks t LEFT JOIN planning428_progress p '
                    'ON p.task_id=t.task_id WHERE p.task_id IS NULL OR p.version!=t.version '
                    'OR p.next_check_at<=? ORDER BY (t.task_id<=?),t.task_id LIMIT ?',
                    (self.clock(), cursor, limit)).fetchall()]
            for task_id in ids:
                try:
                    self._step_task(task_id)
                except Exception as error:
                    # A malformed task cannot kill the Warden tick or expose
                    # raw model/provider text to operator status.
                    version = self.journal.status(task_id)['journal_version']
                    self._record(task_id, version, 'PLANNING_ERROR', error_type=type(error).__name__, delay=60)
                with self.journal._write() as conn:
                    conn.execute('INSERT INTO planning428_cursor VALUES(1,?) '
                        'ON CONFLICT(singleton) DO UPDATE SET task_id=excluded.task_id', (task_id,))
            return len(ids)
        finally:
            self._lock.release()
