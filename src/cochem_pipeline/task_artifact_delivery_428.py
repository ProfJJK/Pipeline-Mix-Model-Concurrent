"""Fenced delivery of verified planning code through existing Git safeguards.

Only a shared-pool TASK_DELIVER worker executes Git plumbing. Enqueue/status are
database-only. The default is an immutable private commit and binary patch for
review; automatic ref integration is limited to registry-proven isolated copies.
The owner's original checkout is never an integration target.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import threading
import time

from .coding import CodingProject, digest, validate_project_files, within
from .workflow_428 import _id


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


class _SourceChanged(ValueError):
    pass


class TaskArtifactDeliveryRuntime:
    def __init__(self, runtime, *, artifact_runtime=None):
        self.runtime, self.store = runtime, runtime.store
        self.artifacts = artifact_runtime or runtime.task_artifacts
        with self.store._write() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS task428_delivery_intents(
                    delivery_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, producer_job_id TEXT NOT NULL,
                    binding_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task428_delivery_staging(
                    delivery_id TEXT PRIMARY KEY, staged_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task428_delivery_results(
                    delivery_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL, output_json TEXT NOT NULL, evidence_json TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS task428_delivery_intent_no_update BEFORE UPDATE ON task428_delivery_intents
                BEGIN SELECT RAISE(ABORT,'task delivery intent is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_delivery_intent_no_delete BEFORE DELETE ON task428_delivery_intents
                BEGIN SELECT RAISE(ABORT,'task delivery intent is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_delivery_staging_no_update BEFORE UPDATE ON task428_delivery_staging
                BEGIN SELECT RAISE(ABORT,'task delivery staging is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_delivery_staging_no_delete BEFORE DELETE ON task428_delivery_staging
                BEGIN SELECT RAISE(ABORT,'task delivery staging is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_delivery_result_no_update BEFORE UPDATE ON task428_delivery_results
                BEGIN SELECT RAISE(ABORT,'task delivery result is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_delivery_result_no_delete BEFORE DELETE ON task428_delivery_results
                BEGIN SELECT RAISE(ABORT,'task delivery result is immutable'); END;
            ''')

    def _binding(self, producer_job_id):
        producer = self.store.get(_id(producer_job_id))
        if not self.artifacts.requires_terminal_verification(producer['payload']):
            raise ValueError('Delivery requires a final producer with controller verification')
        proof = self.artifacts.verification_outcome(producer)
        if proof.get('status') != 'VERIFIED' or proof.get('verification_kind') != 'coding_green':
            raise ValueError('Coding delivery requires completed exact RED/GREEN verification')
        intent = producer['payload']['planning_intent']
        capture = self.artifacts._capture(intent['task_id'])
        project = CodingProject.from_dict(capture['project_id'], capture['project'])
        current = self.runtime.coding.projects().get(capture['project_id'])
        if current is None or current.as_dict() != project.as_dict():
            raise ValueError('Registered delivery project changed after capture')
        accepted = self.artifacts.accepted_snapshot(producer)
        if proof['source_snapshot_sha256'] != accepted['snapshot_sha256']:
            raise ValueError('Verified delivery snapshot differs from producer bytes')
        baseline = self.store.coding_files(capture['snapshot_sha256'])
        files = self.store.coding_files(accepted['snapshot_sha256'])
        validate_project_files(files)
        changed = sorted(path for path in set(baseline) | set(files) if baseline.get(path) != files.get(path))
        if any(not within(path, (*project.allowed_paths, *project.test_paths))
               or (path in baseline and within(path, project.test_paths)) for path in changed):
            raise ValueError('Delivery contains out-of-scope changes or modified protected tests')
        registry = getattr(self.runtime.coding, 'registry', None)
        provenance = registry.delivery_provenance(project.project_id) if registry is not None else None
        if provenance is not None and provenance['prepared_project'] != project.as_dict():
            raise ValueError('Delivery does not match the exact prepared project')
        return dict(schema='cochem-task-delivery-binding/4.2.8', task_id=intent['task_id'],
            project_id=project.project_id, project=project.as_dict(), capture=capture,
            producer_job_id=producer_job_id, producer_attempt_id=producer['attempt_id'],
            producer_fencing_token=producer['fencing_token'], producer_output_sha256=digest(producer['output']),
            source_snapshot_sha256=accepted['snapshot_sha256'], physical_proof=proof,
            changed_paths=changed, preparation=provenance,
            integration_policy='ISOLATED_PREPARED_ONLY' if provenance and project.auto_integrate else 'EXPORT_FOR_REVIEW')

    def enqueue(self, producer_job_id):
        producer = self.store.get(_id(producer_job_id))
        task_id = producer['payload']['planning_intent']['task_id']
        if self.artifacts._capture(task_id)['project'] is None:
            return dict(status='NOT_APPLICABLE', original_repository_integration='NOT_APPLICABLE')
        binding = self._binding(producer_job_id)
        delivery_id = 'delivery428-' + digest(binding)[:40]
        root_id, job_id = delivery_id + '-root', delivery_id + '-node'
        payload = dict(schema='cochem-task-delivery/4.2.8', delivery_id=delivery_id,
                       task_id=binding['task_id'], producer_job_id=producer_job_id)
        raw = encoded(binding)
        with self.store._write() as conn:
            if conn.execute('SELECT 1 FROM task428_cancelled_tasks WHERE task_id=?', (binding['task_id'],)).fetchone():
                return dict(status='TASK_DELIVERY_CANCELLED', delivery_id=delivery_id)
            prior = conn.execute('SELECT binding_json FROM task428_delivery_intents WHERE delivery_id=?', (delivery_id,)).fetchone()
            if prior is None:
                conn.execute('INSERT INTO task428_delivery_intents VALUES(?,?,?,?)',
                             (delivery_id, binding['task_id'], producer_job_id, raw))
                self.store._insert(conn, root_id, root_id, None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS',
                                   dict(workflow_type='task_delivery428', task_id=binding['task_id']))
                self.store._insert(conn, job_id, root_id, root_id, 'TASK_DELIVER', 'PENDING', payload)
            elif prior[0] != raw or self.store._get(conn, job_id)['payload'] != payload:
                raise ValueError('Existing delivery has different immutable authority')
        return self.status(delivery_id)

    def status(self, delivery_id):
        _id(delivery_id)
        with self.store._connection() as conn:
            row = conn.execute('SELECT output_json FROM task428_delivery_results WHERE delivery_id=?', (delivery_id,)).fetchone()
            if row:
                return json.loads(row[0])
            job = self.store._get(conn, delivery_id + '-node')
        return dict(status='TASK_DELIVERY_HELD' if job['status'] in ('FAILED', 'BLOCKED') else 'WAITING_FOR_TASK_DELIVERY',
                    delivery_id=delivery_id, job_id=job['job_id'])

    def _owned(self, conn, node):
        job = self.store._get(conn, node['job_id'])
        if job['kind'] != 'TASK_DELIVER' or not self.store._owned(job, node['attempt_id'], node['fencing_token']):
            raise ValueError('Task delivery requires the current shared-worker fence')
        if job['payload'] != node['payload']:
            raise ValueError('Task delivery worker input changed')
        if conn.execute('SELECT 1 FROM task428_cancelled_tasks WHERE task_id=?', (job['payload']['task_id'],)).fetchone():
            raise ValueError('Cancelled task cannot publish a delivery')
        row = conn.execute('SELECT binding_json FROM task428_delivery_intents WHERE delivery_id=?',
                           (job['payload']['delivery_id'],)).fetchone()
        if row is None:
            raise ValueError('Task delivery has no controller-owned intent')
        binding = json.loads(row[0])
        if (job['payload']['schema'] != 'cochem-task-delivery/4.2.8'
                or job['payload']['delivery_id'] != 'delivery428-' + digest(binding)[:40]
                or any(job['payload'][key] != binding[key] for key in ('task_id', 'producer_job_id'))):
            raise ValueError('Task delivery intent binding changed')
        return binding

    def run(self, node, heartbeat, cancel_event):
        """Run on an existing non-Docker shared worker; no new execution pool."""
        from .coding_git import GitStager, RepositorySnapshot, _reject_links
        from .worker import ExecutionRevokedError
        with self.store._connection() as conn:
            binding = self._owned(conn, node)
        if binding != self._binding(binding['producer_job_id']):
            raise ValueError('Verified delivery inputs changed before execution')
        stopped = threading.Event()
        def renew():
            while not stopped.wait(max(.1, min(5, self.runtime.config.lease_seconds / 3))):
                if not heartbeat():
                    cancel_event.set()
                    return
        monitor = threading.Thread(target=renew, daemon=True)
        monitor.start()
        def current():
            if cancel_event.is_set() or not heartbeat():
                raise ExecutionRevokedError('Task delivery was cancelled or lost its lease')
            with self.store._connection() as conn:
                self._owned(conn, node)
        try:
            current()
            capture = binding['capture']
            original = self.store.coding_files(capture['snapshot_sha256'])
            baseline = RepositorySnapshot.from_dict(capture['repository'], original)
            files = self.store.coding_files(binding['source_snapshot_sha256'])
            root = Path(self.runtime.config.private_root) / 'task-deliveries-git'
            stager = GitStager(root, git_executable=self.runtime.config.git_executable)
            staged = stager.stage(baseline, files, workflow_id=node['payload']['delivery_id'], chunk_id='verified-result',
                                  modes=capture['modes'], message='Verified planning task artifact', max_changed_lines=None)
            current()
            patch = Path(staged['patch_path'])
            _reject_links(patch)
            if root.absolute() not in patch.absolute().parents or hashlib.sha256(patch.read_bytes()).hexdigest() != staged['patch_sha256']:
                raise ValueError('Task delivery patch is not the exact controller-owned artifact')
            with self.store._write() as conn:
                self._owned(conn, node)
                old = conn.execute('SELECT staged_json FROM task428_delivery_staging WHERE delivery_id=?',
                                   (node['payload']['delivery_id'],)).fetchone()
                if old is None:
                    conn.execute('INSERT INTO task428_delivery_staging VALUES(?,?)',
                                 (node['payload']['delivery_id'], encoded(staged)))
                elif old[0] != encoded(staged):
                    raise ValueError('Existing delivery staging differs; preserve prior evidence')
            source_check, integration = None, None
            status = 'EXPORTED_FOR_REVIEW'
            if binding['integration_policy'] == 'ISOLATED_PREPARED_ONLY':
                registry = self.runtime.coding.registry
                try:
                    source_check = registry.verify_delivery_source(binding['project_id'])
                except (ValueError, OSError):
                    source_check = dict(status='SOURCE_CHANGED_OR_UNVERIFIED')
                permit_cas = source_check['status'] == 'SOURCE_CAPTURE_MATCHES'
                @contextmanager
                def guarded():
                    current()
                    if permit_cas:
                        # The only write target is the prepared private copy.
                        # Re-read original head/branch/scoped dirty inputs at CAS.
                        try:
                            registry.verify_delivery_source(binding['project_id'])
                        except (ValueError, OSError) as error:
                            raise _SourceChanged('Original source changed before private integration') from error
                    with self.store._write() as conn:
                        self._owned(conn, node)
                        yield
                try:
                    # auto_integrate=False can recognize an earlier successful
                    # CAS after a crash, but cannot advance an unmodified branch.
                    integration = stager.integrate(baseline, staged, auto_integrate=permit_cas, cas_guard=guarded)
                except _SourceChanged:
                    source_check = dict(status='SOURCE_CHANGED_OR_UNVERIFIED')
                if integration is not None and integration['status'] == 'INTEGRATED':
                    status = 'INTEGRATED_ISOLATED_REPOSITORY'
            current()
            output = dict(schema='cochem-task-delivery-result/4.2.8', status=status,
                delivery_id=node['payload']['delivery_id'], job_id=node['job_id'],
                producer_job_id=binding['producer_job_id'], source_snapshot_sha256=binding['source_snapshot_sha256'],
                patch_path=staged['patch_path'], patch_sha256=staged['patch_sha256'],
                staging_repository=staged['staging_repository'], result_commit=staged['result_commit'],
                changed_paths=binding['changed_paths'], source_check=source_check,
                original_checkout_modified=False, original_repository_integration='NOT_ATTEMPTED',
                integration_policy=binding['integration_policy'])
            evidence = dict(schema='cochem-task-delivery-evidence/4.2.8', binding_sha256=digest(binding),
                staged=staged, integration=integration, source_check=source_check, cleanup_verified=True,
                job_id=node['job_id'], attempt_id=node['attempt_id'], fencing_token=node['fencing_token'],
                output_sha256=digest(output))
            self.store.record_coding_attempt_evidence(node, evidence)
            receipt = dict(executor='task_delivery', job_id=node['job_id'], attempt_id=node['attempt_id'],
                fencing_token=node['fencing_token'], output_sha256=digest(output), cleanup_verified=True, finished_at=time.time())
            return output, receipt, evidence
        finally:
            stopped.set()
            monitor.join(timeout=2)

    def complete(self, node, output, receipt, evidence):
        """Only the shared controller worker can publish its cleaned-up result."""
        from . import routing_store as routes
        from .coding_git import _reject_links
        patch = Path(output['patch_path'])
        _reject_links(patch)
        if ((Path(self.runtime.config.private_root) / 'task-deliveries-git').absolute() not in patch.absolute().parents
                or hashlib.sha256(patch.read_bytes()).hexdigest() != output['patch_sha256']):
            raise ValueError('Delivery patch changed before publication')
        with self.store._write() as conn:
            binding = self._owned(conn, node)
            expected_status = ('INTEGRATED_ISOLATED_REPOSITORY' if (evidence.get('integration') or {}).get('status') == 'INTEGRATED'
                               else 'EXPORTED_FOR_REVIEW')
            if (receipt.get('executor') != 'task_delivery' or receipt.get('cleanup_verified') is not True
                    or evidence.get('cleanup_verified') is not True or evidence.get('binding_sha256') != digest(binding)
                    or output.get('delivery_id') != node['payload']['delivery_id']
                    or output.get('original_checkout_modified') is not False
                    or output.get('original_repository_integration') != 'NOT_ATTEMPTED'
                    or output.get('status') != expected_status
                    or output.get('source_snapshot_sha256') != binding['source_snapshot_sha256']
                    or output.get('integration_policy') != binding['integration_policy']
                    or output.get('changed_paths') != binding['changed_paths']
                    or any(output.get(key) != evidence.get('staged', {}).get(key)
                           for key in ('patch_path', 'patch_sha256', 'staging_repository', 'result_commit'))
                    or any(record.get(key) != node[key] for record in (receipt, evidence)
                           for key in ('job_id', 'attempt_id', 'fencing_token'))
                    or any(record.get('output_sha256') != digest(output) for record in (receipt, evidence))):
                raise ValueError('Task delivery receipt does not bind its exact result')
            if conn.execute('SELECT 1 FROM pipeline_execution_cleanup WHERE job_id=? AND cleared_at IS NULL',
                            (node['job_id'],)).fetchone():
                raise ValueError('Task delivery cleanup has not completed')
            recorded = conn.execute('SELECT evidence_json,sha256 FROM coding_attempt_evidence '
                'WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                (node['job_id'], node['attempt_id'], node['fencing_token'])).fetchone()
            staged = conn.execute('SELECT staged_json FROM task428_delivery_staging WHERE delivery_id=?',
                                 (node['payload']['delivery_id'],)).fetchone()
            if (recorded is None or recorded['evidence_json'] != encoded(evidence)
                    or recorded['sha256'] != digest(evidence) or staged is None or staged[0] != encoded(evidence['staged'])):
                raise ValueError('Task delivery requires its durable stage and observed attempt evidence')
            conn.execute('INSERT INTO coding_evidence VALUES(?,?,?)', (node['job_id'], encoded(evidence), digest(evidence)))
            conn.execute('INSERT INTO pipeline_outputs VALUES(?,?,?,?,?,?,?,?)',
                (node['job_id'], node['attempt_id'], node['fencing_token'], None,
                 encoded(output), encoded(receipt), digest(output), time.time()))
            conn.execute('INSERT INTO task428_delivery_results VALUES(?,?,?,?,?,?)',
                (node['payload']['delivery_id'], node['job_id'], node['attempt_id'], node['fencing_token'],
                 encoded(output), encoded(evidence)))
            conn.execute("UPDATE pipeline_jobs SET status='COMPLETED',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                         (time.time(), node['job_id']))
            routes.release(conn, node['job_id'], 'completed', 'COMPLETED')
            self.store._event(conn, node, 'COMPLETED', output_sha256=digest(output), evidence_sha256=digest(evidence))
            root = self.store._get(conn, node['workflow_id'])
            if root['payload'].get('workflow_type') != 'task_delivery428':
                raise ValueError('Task delivery does not belong to its controller workflow')
            conn.execute("UPDATE pipeline_jobs SET status='COMPLETED',updated_at=? WHERE job_id=?", (time.time(), root['job_id']))
            self.store._event(conn, root, 'WORKFLOW_COMPLETED', delivery_id=node['payload']['delivery_id'])
        return output
