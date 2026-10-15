"""Bounded planning progression on the existing board, with no native executor.

The controller imports only committed, cleaned-up board results. Research and
human approval remain separate trusted evidence ports. Neither an HTTP caller
nor a planning model can manufacture those receipts. Execution materialization
is a separate consumer; READY here means the plan, not the deliverable, is ready.
"""
from dataclasses import dataclass
import hashlib
import json
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
        attempt_ledger=None,
        attempt_runtime=None,
        dossier_store=None,
        pivot_runtime=None,
        fracture_runtime=None,
        decision_store=None,
        repair_queue=None,
        audit_runtime=None,
        owner_approval_broker=None,
        artifact_runtime=None,
        outcome_runtime=None,
    ):
        self.journal, self.store, self.clock = journal, store, clock
        self.research_runtime = research_runtime
        self.execution_runtime = execution_runtime
        self.release_runtime = release_runtime
        self.attempt_ledger = attempt_ledger
        self.attempt_runtime = attempt_runtime
        if execution_runtime is not None and attempt_runtime is not None:
            execution_runtime.attempt_accounting = attempt_runtime
        self.dossier_store = dossier_store
        self.pivot_runtime = pivot_runtime
        self.fracture_runtime = fracture_runtime
        self.decision_store = decision_store
        self.repair_queue = repair_queue
        self.audit_runtime = audit_runtime
        self.owner_approval_broker = owner_approval_broker
        self.artifact_runtime = artifact_runtime
        if outcome_runtime is None and attempt_runtime is not None:
            from .planning_outcomes_428 import PlanningOutcomeRuntime
            outcome_runtime = PlanningOutcomeRuntime(journal, store, attempt_runtime,
                research_runtime=research_runtime, dossier_store=dossier_store, decision_store=decision_store,
                artifact_runtime=artifact_runtime)
        self.outcome_runtime = outcome_runtime
        self.pivot_bridge = None
        if outcome_runtime is not None and pivot_runtime is not None:
            from .planning_pivots_428 import PlanningPivotRuntime
            self.pivot_bridge = PlanningPivotRuntime(journal, store, outcome_runtime, pivot_runtime)
            if self.release_runtime is not None:
                self.release_runtime.board.pivot_context_provider = self.pivot_bridge.dispatch_context
        self._research_thread = None
        self.gateway = PlanningGateway(journal, store, artifact_runtime=artifact_runtime)
        self.journal.model_result = self.gateway.model_result
        if research_runtime is not None and self.journal.search_result is None:
            self.journal.search_result = research_runtime.evidence_store.load_for_journal
        if owner_approval_broker is not None and self.journal.owner_receipt is None:
            self.journal.owner_receipt = owner_approval_broker.load_for_journal
        self._lock = threading.Lock()
        with journal._write() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS planning428_progress(
                    task_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                    status TEXT NOT NULL, job_id TEXT, research_id TEXT,
                    error_type TEXT, checked_at REAL NOT NULL, next_check_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS planning428_cursor(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), task_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS planning428_cancel_targets(
                    task_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0, error_type TEXT,
                    PRIMARY KEY(task_id,target_id,kind));
                CREATE TABLE IF NOT EXISTS planning428_completion_audits(
                    task_id TEXT PRIMARY KEY, result_json TEXT NOT NULL);
            ''')

    @classmethod
    def from_runtime(cls, runtime):
        import secrets
        from .attempt_runtime_428 import AttemptAccountingRuntime
        from .completion_audit_428 import CompletionAuditRuntime
        from .failure_dossier_428 import FailureDossierStore
        from .fracture_runtime_428 import FractureRuntime
        from .owner_approval_428 import OwnerApprovalBroker
        from .pivot_runtime_428 import PivotRuntime
        from .repair_queue_428 import RepairQueue
        from .research_evidence_428 import ResearchEvidenceStore
        from .research_runtime_428 import ResearchRuntime
        from .research_search_428 import ResearchSearchClient
        from .task_decisions_428 import LockedTaskDecisionStore
        from .task_execution_428 import SimpleTaskExecutionRuntime
        from .task_release_428 import TaskReleaseRuntime
        from .microtask_board_428 import MicrotaskBoardRuntime
        from .workflow_428 import AttemptLedger

        spec = runtime.config.task_planning
        catalog = getattr(runtime, 'accepted_task_catalog', None)
        if catalog is None:
            catalog = spec.read_catalog()
        secret_file = runtime.config.private_root / 'owner_approval.secret'
        shared_tokens = set()
        token_file = getattr(runtime.config, 'token_file', None)
        if token_file is not None:
            try:
                tok = Path(token_file).read_text(encoding='utf-8').strip()
                if tok:
                    shared_tokens.add(tok)
            except OSError:
                pass
        if secret_file.is_file():
            owner_secret = secret_file.read_text(encoding='utf-8').strip()
        else:
            owner_secret = 'owner428-' + secrets.token_hex(32)
            try:
                with secret_file.open('x', encoding='utf-8') as out:
                    out.write(owner_secret + '\n')
            except FileExistsError:
                owner_secret = secret_file.read_text(encoding='utf-8').strip()
        owner_broker = OwnerApprovalBroker(
            runtime.config.private_root / 'owner428.db',
            owner_secret=owner_secret,
            shared_agent_tokens=shared_tokens,
        )
        runtime.owner_approval_broker = owner_broker
        journal = PlanningJournal(
            runtime.config.private_root / 'planning428.db',
            catalog,
            flash_context_limit=spec.flash_context_limit,
            owner_receipt=owner_broker.load_for_journal,
        )
        ev_store = ResearchEvidenceStore(runtime.config.private_root / 'research428.db')
        res_runtime = ResearchRuntime(
            ev_store,
            ResearchSearchClient(),
            knowledge_service=getattr(runtime, 'knowledge', None),
            knowledge_authority=getattr(runtime, 'knowledge_authority', None),
        )
        ledger = AttemptLedger(runtime.config.private_root / 'attempts428.db')
        att_runtime = AttemptAccountingRuntime(ledger, store=runtime.store)
        artifact_runtime = getattr(runtime, 'task_artifacts', None)
        artifact_args = {'artifact_runtime': artifact_runtime} if artifact_runtime is not None else {}
        exec_runtime = SimpleTaskExecutionRuntime(journal, runtime.store,
                                                 attempt_accounting=att_runtime, **artifact_args)
        board = MicrotaskBoardRuntime(journal, runtime.store, owner_broker=owner_broker,
                                      attempt_ledger=att_runtime, **artifact_args)
        rel_runtime = TaskReleaseRuntime(journal, runtime.store, board=board,
                                        owner_broker=owner_broker, **artifact_args)
        dos_store = FailureDossierStore(ledger)
        piv_runtime = PivotRuntime(ledger, catalog, dossier_store=dos_store)
        frac_runtime = FractureRuntime(ledger, catalog, dossier_store=dos_store, job_store=runtime.store)
        dec_store = LockedTaskDecisionStore(ledger, dossier_store=dos_store)
        rep_queue = RepairQueue(
            runtime.config.private_root / 'repair428.db',
            catalog,
            profiles={
                'repair_claude': {'provider': 'claude', 'quota_pool': 'anthropic'},
                'repair_codex': {'provider': 'codex', 'quota_pool': 'openai'},
                'repair_agy': {'provider': 'gemini', 'quota_pool': 'google'},
            },
            normal_profile_ids={'slot1', 'slot2', 'slot3', 'slot4', 'slot5', 'slot6'},
            verify_reservation=cls._unconfigured_repair_verifier,
            verify_commit=cls._unconfigured_repair_verifier,
        )
        aud_runtime = CompletionAuditRuntime(runtime.config.private_root / 'audit428.db', catalog, rep_queue)
        return cls(
            journal,
            runtime.store,
            research_runtime=res_runtime,
            execution_runtime=exec_runtime,
            release_runtime=rel_runtime,
            attempt_ledger=ledger,
            attempt_runtime=att_runtime,
            dossier_store=dos_store,
            pivot_runtime=piv_runtime,
            fracture_runtime=frac_runtime,
            decision_store=dec_store,
            repair_queue=rep_queue,
            audit_runtime=aud_runtime,
            owner_approval_broker=owner_broker,
            artifact_runtime=artifact_runtime,
        )

    @staticmethod
    def _unconfigured_repair_verifier(*_args):
        raise RuntimeError('Independent repair execution authority is not configured')

    def kick_research_worker(self) -> bool:
        if self.research_runtime is None or not hasattr(self.research_runtime, 'has_due_work'):
            return False
        if self._research_thread is not None and self._research_thread.is_alive():
            return False
        if not self.research_runtime.has_due_work():
            return False

        def _worker():
            try:
                count = self.research_runtime.step_worker()
                if count > 0:
                    now = self.clock()
                    with self.journal._write() as conn:
                        conn.execute(
                            "UPDATE planning428_progress SET next_check_at=? WHERE status='WAITING_FOR_RESEARCH'",
                            (now,),
                        )
            except Exception:
                pass

        self._research_thread = threading.Thread(target=_worker, name='research-428', daemon=True)
        self._research_thread.start()
        return True

    def close(self) -> None:
        thread = self._research_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)


    def has_task(self, task_id) -> bool:
        return self.journal.has_task(task_id)

    def submit(self, objective, task_id=None, *, project_id=None, requested_requirements=None):
        # No catalog, tier, approval, profile or dispatch arguments are accepted.
        task_id = _id(task_id if task_id is not None else 'task428-' + uuid.uuid4().hex)
        if self.artifact_runtime is not None:
            self.artifact_runtime.prepare_task(task_id, project_id)
        self.journal.create(task_id, objective, project_id=project_id, requested_requirements=requested_requirements)
        return self.task_status(task_id)

    def cancel(self, task_id):
        _id(task_id)
        current = self.task_status(task_id)
        job_id = (current.get('controller') or {}).get('job_id')
        cancelled_jobs = set()
        if job_id:
            cancelled_jobs.add(job_id)
        # A content reviewer or verification producer may no longer be the
        # single progress-row job. Its captured task identity is authoritative.
        with self.store._connection() as conn:
            cancelled_jobs.update(row[0] for row in conn.execute(
                "SELECT job_id FROM pipeline_jobs WHERE kind='TASK_PLAN' "
                "AND json_extract(payload_json,'$.planning_intent.task_id')=?", (task_id,)))
        if self.release_runtime is not None and hasattr(self.release_runtime, 'board'):
            snap = self.release_runtime.board.board_status(task_id)
            for node in list(snap.get('nodes') or ()) + list(snap.get('batches') or ()):
                if node.get('job_id'):
                    cancelled_jobs.add(node['job_id'])
        if self.pivot_bridge is not None:
            cancelled_jobs.update(self.pivot_bridge.cancellation_targets(task_id))
        targets = [(jid, 'job') for jid in sorted(cancelled_jobs)]
        if self.artifact_runtime is not None:
            targets.append((task_id, 'artifacts'))
        research_id = (current.get('controller') or {}).get('research_id')
        if research_id:
            targets.append((research_id, 'research'))
        if self.outcome_runtime is not None:
            targets.extend((row['research_id'], 'research') for row in self.outcome_runtime.status(task_id)
                           if row.get('research_id'))
        # Persist cancellation obligations before changing the task stage. A
        # process interruption cannot turn an unfinished cancellation into success.
        with self.journal._write() as conn:
            conn.executemany('INSERT OR IGNORE INTO planning428_cancel_targets(task_id,target_id,kind) '
                             'VALUES(?,?,?)', [(task_id, target, kind) for target, kind in targets])
        state = self.journal.cancel(task_id)
        self._reconcile_cancellation(task_id, state['journal_version'])
        return self.task_status(task_id)

    def _reconcile_cancellation(self, task_id, version):
        with self.journal._write() as conn:
            targets = conn.execute('SELECT target_id,kind FROM planning428_cancel_targets '
                                   'WHERE task_id=? AND done=0', (task_id,)).fetchall()
        pending = False
        for target in targets:
            try:
                if target['kind'] == 'job':
                    job = self.store.get(target['target_id'])
                    self.store.cancel_workflow(job['workflow_id'])
                elif target['kind'] == 'artifacts':
                    if self.artifact_runtime is None:
                        raise RuntimeError('Artifact cancellation port is not configured')
                    self.artifact_runtime.cancel_task(target['target_id'])
                elif self.research_runtime is not None:
                    self.research_runtime.cancel(target['target_id'])
                else:
                    raise RuntimeError('Research cancellation port is not configured')
                error_type = None
            except Exception as error:
                pending = True
                error_type = type(error).__name__
            with self.journal._write() as conn:
                conn.execute('UPDATE planning428_cancel_targets SET done=?,error_type=? '
                             'WHERE task_id=? AND target_id=? AND kind=?',
                             (int(error_type is None), error_type, task_id, target['target_id'], target['kind']))
        self._record(task_id, version, 'CANCELLATION_PENDING' if pending else 'CANCELLED',
                     delay=5 if pending else 3600)

    def notify_job_changed(self, job_id):
        if not isinstance(job_id, str) or not job_id:
            return
        now = self.clock()
        with self.journal._write() as conn:
            conn.execute('UPDATE planning428_progress SET next_check_at=? WHERE job_id=?', (now, job_id))

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
        with self.journal._write() as conn:
            audit = conn.execute('SELECT result_json FROM planning428_completion_audits WHERE task_id=?',
                                 (task_id,)).fetchone()
        if audit is not None:
            result['completion_audit'] = json.loads(audit[0])
        if self.outcome_runtime is not None:
            result['attempt_boundaries'] = self.outcome_runtime.status(task_id)
            result['unclassified_outcome_holds'] = self.outcome_runtime.unresolved_releases(task_id)
        if self.decision_store is not None and self.attempt_ledger is not None:
            try:
                lstate = self.attempt_ledger.status(task_id)
                if lstate.get('stage') == 'LOCKED':
                    packets = self.decision_store.status_projection(task_id)
                    if packets:
                        result['locked_decision'] = packets[0]
            except (ValueError, KeyError):
                pass
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
        if self.outcome_runtime is not None:
            self.outcome_runtime.reconcile_task(task_id)
        if self.pivot_bridge is not None:
            self.pivot_bridge.step(task_id)
        intent = self.journal.intent(task_id)
        version, action = intent['version'], intent['action']
        if intent.get('stage') == 'CANCELLED':
            self._reconcile_cancellation(task_id, version)
        elif action == 'model_stage':
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
            audit = self._enqueue_completion_audits(task_id)
            self._record(task_id, version, 'EXECUTION_COMPLETED',
                         delay=30 if audit == 'SKIPPED_AUDIT_CAPACITY' else 3600)
        else:
            status = {'owner_review': 'WAITING_FOR_OWNER_APPROVAL',
                      'jobboard_submission': 'PLAN_READY_EXECUTION_PENDING',
                      'capability_hold': 'CAPABILITY_HOLD'}.get(action, 'PLANNING_HELD')
            self._record(task_id, version, status, delay=30)

    def _enqueue_completion_audits(self, task_id):
        """Enqueue independently sampled work; never manufacture an audit verdict."""
        if self.audit_runtime is None:
            return 'NOT_CONFIGURED'
        with self.journal._write() as conn:
            row = self.journal._read(conn, task_id)
            state, catalog = json.loads(row['state_json']), json.loads(row['catalog_json'])
        if state.get('stage') != 'COMPLETED':
            return 'NOT_COMPLETE'
        artifacts = []
        if self.execution_runtime is not None:
            artifact = self.execution_runtime.get_artifact(task_id)
            if artifact:
                artifacts.append(dict(job_id=artifact['job_id'], profile_id=artifact['profile_id'],
                    output_sha256=artifact['artifact_sha256'], task_types=state['assessment']['task_types'],
                    expected_requirements=[r['id'] for r in state['document']['requirements']]))
        if self.release_runtime is not None and self.release_runtime.get_release(task_id):
            for node in self.release_runtime.board.board_status(task_id)['nodes']:
                if node['status'] == 'COMPLETED' and node.get('job_id'):
                    artifacts.append(dict(job_id=node['job_id'],
                        profile_id=(node.get('output') or {}).get('profile_id'),
                        output_sha256=node['artifact_sha256'], task_types=node['task_types'],
                        expected_requirements=node['requirement_ids']))
        if not artifacts:
            raise ValueError('Completed task has no recorded execution evidence for audit')
        results = []
        for item in artifacts:
            job_id = item['job_id']
            with self.store._connection() as conn:
                job = self.store._get(conn, job_id)
                cleanup = conn.execute('SELECT cleared_at FROM pipeline_execution_cleanup '
                    'WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                    (job_id, job['attempt_id'], job['fencing_token'])).fetchone()
            if job['status'] != 'COMPLETED' or not job.get('receipt') or cleanup is None or cleanup[0] is None:
                raise ValueError('Completion audit requires a committed result and verified native cleanup')
            profile = catalog['models'].get(item.pop('profile_id'))
            if profile is None:
                raise ValueError('Completion producer is absent from the task catalog capture')
            result = self.audit_runtime.enqueue_completion(task_id=task_id,
                producer_model_family=profile['family'], **item)
            results.append({'audit_key': result['audit_key'], 'status': result['status'],
                            'sampled': result['sampled']})
        # Status says QUEUED/NOT_SAMPLED, never audited merely because it was enqueued.
        with self.journal._write() as conn:
            conn.execute('INSERT INTO planning428_completion_audits VALUES(?,?) '
                         'ON CONFLICT(task_id) DO UPDATE SET result_json=excluded.result_json',
                         (task_id, json.dumps(results, sort_keys=True)))
        return ('SKIPPED_AUDIT_CAPACITY' if any(r['status'] == 'SKIPPED_AUDIT_CAPACITY' for r in results)
                else 'ENQUEUED')

    def step(self, limit=8):
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('Planning poll must be bounded to 1..32 tasks')
        if not self._lock.acquire(blocking=False):
            return 0
        try:
            if self.attempt_runtime is not None and hasattr(self.attempt_runtime, 'reconcile_outbox'):
                self.attempt_runtime.reconcile_outbox()
            if self.fracture_runtime is not None and hasattr(self.fracture_runtime, 'reconcile_partial_fractures'):
                self.fracture_runtime.reconcile_partial_fractures()
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
