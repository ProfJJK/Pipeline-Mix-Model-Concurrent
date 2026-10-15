"""Controller-owned task staging and queued physical verification.

Model jobs only propose bytes. Captured projects, inherited fragments and
winning attempt identities stay in the private board database. Verification is
a separate job in the existing shared admission pool, never scheduler-thread
code execution or a second worker pool.
"""
from __future__ import annotations

from copy import deepcopy
import json
import threading
import time

from .coding import (CodingProject, bind_test_identities, digest, manifest,
                     materialize, read_workspace, source_context,
                     validate_project_files, validate_production_coding_project, within)
from .task_artifacts_428 import stage_fragment_workspace, validate_fragment_deliverables
from .task_verification_428 import (requirement_test_names, verify_artifact_evidence,
                                    verify_task_test_evidence)


class TaskArtifactRuntime:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store
        with self.store._write() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS task428_source_captures(
                    task_id TEXT PRIMARY KEY, project_id TEXT, capture_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task428_fragment_attempts(
                    job_id TEXT NOT NULL, attempt_id TEXT NOT NULL, fencing_token INTEGER NOT NULL,
                    task_id TEXT NOT NULL, microtask_id TEXT, generation TEXT,
                    output_sha256 TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, PRIMARY KEY(job_id,attempt_id,fencing_token));
                CREATE INDEX IF NOT EXISTS task428_fragment_lookup ON
                    task428_fragment_attempts(task_id,microtask_id,generation);
            ''')

    def prepare_task(self, task_id, project_id):
        with self.store._connection() as conn:
            old = conn.execute('SELECT project_id FROM task428_source_captures WHERE task_id=?', (task_id,)).fetchone()
        if old is not None:
            if old['project_id'] != project_id:
                raise ValueError('Task project capture is immutable')
            return
        capture, files = dict(project=None, repository=None, modes={}), {}
        if project_id is not None:
            if self.runtime.coding is None:
                raise ValueError('Registered coding execution is unavailable')
            project = validate_production_coding_project(self.runtime.coding.projects()[project_id])
            from .coding_git import capture_repository
            snap = capture_repository(project.repository, project.branch,
                                      git_executable=self.runtime.config.git_executable)
            validate_project_files(snap.files)
            files = snap.files
            capture.update(project=project.as_dict(), repository=snap.as_dict(), modes=snap.modes)
        with self.store._write() as conn:
            capture['snapshot_sha256'] = self.store._snapshot(conn, files)
            encoded = json.dumps(capture, sort_keys=True)
            conn.execute('INSERT OR IGNORE INTO task428_source_captures VALUES(?,?,?)', (task_id, project_id, encoded))
            row = conn.execute('SELECT * FROM task428_source_captures WHERE task_id=?', (task_id,)).fetchone()
            if row['project_id'] != project_id or row['capture_json'] != encoded:
                raise ValueError('Concurrent task source capture differs')

    def _capture(self, task_id):
        with self.store._connection() as conn:
            row = conn.execute('SELECT * FROM task428_source_captures WHERE task_id=?', (task_id,)).fetchone()
            if row is None:
                raise ValueError('Task is missing its immutable source capture')
            capture = json.loads(row['capture_json'])
            capture['project_id'] = row['project_id']
            return capture

    def planning_context(self, task_id):
        capture = self._capture(task_id)
        if capture['project'] is None:
            return {'execution_mode': 'content_artifacts',
                    'verification_scope': 'content integrity and independent review; no external action executor'}
        project = CodingProject.from_dict(capture['project_id'], capture['project'])
        files = self.store.coding_files(capture['snapshot_sha256'])
        return dict(execution_mode='registered_coding', project_id=capture['project_id'],
                    allowed_paths=list(project.allowed_paths), test_paths=list(project.test_paths),
                    source=source_context(files, {}, project),
                    delivery='isolated verified snapshot; original repository integration requires a concurrent-change check')

    @staticmethod
    def handles(node):
        return node['kind'] == 'TASK_PLAN' and (node['payload'].get('planning_intent') or {}).get('stage') in (
            'SIMPLE_EXECUTION', 'MICROTASK_EXECUTION')

    def accepted_snapshot(self, job):
        with self.store._connection() as conn:
            fresh = self.store._get(conn, job['job_id'])
            row = conn.execute('SELECT * FROM task428_fragment_attempts WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                (fresh['job_id'], fresh['attempt_id'], fresh['fencing_token'])).fetchone()
            cleanup = conn.execute('SELECT cleared_at FROM pipeline_execution_cleanup WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                (fresh['job_id'], fresh['attempt_id'], fresh['fencing_token'])).fetchone()
            if (fresh['status'] != 'COMPLETED' or row is None or cleanup is None or cleanup['cleared_at'] is None
                    or row['output_sha256'] != digest(fresh['output'])):
                raise ValueError('Task needs physical staging evidence for its winning cleaned-up attempt')
            return dict(row)

    def _inputs(self, node):
        payload, intent = node['payload'], node['payload']['planning_intent']
        capture = self._capture(intent['task_id'])
        project = (CodingProject.from_dict(capture['project_id'], capture['project'])
                   if capture['project'] is not None else None)
        baseline = self.store.coding_files(capture['snapshot_sha256'])
        before, writers, conflicts = dict(baseline), {}, []
        for dep, output in sorted(payload.get('predecessor_outputs', {}).items()):
            with self.store._connection() as conn:
                rows = conn.execute('''SELECT j.job_id FROM task428_fragment_attempts a JOIN pipeline_jobs j
                    ON j.job_id=a.job_id AND j.attempt_id=a.attempt_id AND j.fencing_token=a.fencing_token
                    WHERE a.task_id=? AND a.microtask_id=? AND a.generation=? AND j.status='COMPLETED' ''',
                    (intent['task_id'], dep, intent['plan_generation_sha256'])).fetchall()
            if len(rows) != 1:
                raise ValueError('Assigned predecessor lacks one accepted physical snapshot')
            prior = self.store.get(rows[0]['job_id'])
            if prior['output']['artifact_text'] != output['artifact_text']:
                raise ValueError('Predecessor commitment changed')
            inherited = self.store.coding_files(self.accepted_snapshot(prior)['snapshot_sha256'])
            for path, data in inherited.items():
                if baseline.get(path) != data:
                    writers.setdefault(path, []).append((dep, data))
        for path, versions in writers.items():
            if len({data for _, data in versions}) == 1:
                before[path] = versions[0][1]
            else:
                if payload.get('microtask_node', {}).get('role') != 'assembly':
                    raise ValueError('Conflicting source fragments require explicit assembly')
                conflicts.append(path)
                for dep, data in versions:
                    before['conflicts_428/' + dep + '/' + path] = data
        validate_project_files(before)
        packet = dict(schema='cochem-task-artifact-staging/4.2.8', workspace_files=before,
                      workspace_manifest=manifest(before), assembly_input_sha256=digest(manifest(before)))
        return capture, project, baseline, before, conflicts, packet

    def execution_context(self, payload):
        _, project, _, before, conflicts, _ = self._inputs({'payload': payload})
        intent, micro = payload['planning_intent'], payload.get('microtask_node')
        reqs = micro['requirement_ids'] if micro else [r['id'] for r in intent['task']['document']['requirements']]
        extra = self.planning_context(intent['task_id'])
        if project:
            extra.update(source=source_context(before, {'active_leaf': {'file_targets': (micro or {}).get('deliverables', [])}}, project),
                         required_test_functions=requirement_test_names(reqs),
                         test_rule='Final-test nodes must provide new Python tests with these exact function names, '
                         'real assertions that fail on the original baseline and pass on assembled code. Never edit existing tests.')
        extra['conflicting_paths'] = conflicts
        return extra

    def run(self, node, slot, context, heartbeat, launched, cancel_event, *, on_native_start, on_native_end):
        from .worker import ExecutionRevokedError
        capture, project, baseline, before, conflicts, packet = self._inputs(node)
        if node['payload'].get('execution_context') != self.execution_context(node['payload']):
            raise ValueError('Queued task execution context differs from its immutable source')
        descriptor = self.runtime.ramdisk.workspace(slot)
        descriptor.validate(identity=descriptor.identity)
        workspace = descriptor.root / 'task'
        descriptor.validate(identity=descriptor.identity, cwd=descriptor.root)
        staged = stage_fragment_workspace(workspace, packet)
        intent, micro = node['payload']['planning_intent'], node['payload'].get('microtask_node')
        on_native_start(workspace)
        try:
            output, receipt = self.runtime.runner.run(node, slot, context, heartbeat, launched,
                                                      workspace=workspace, ramdisk_workspace=descriptor)
        finally:
            on_native_end()
        if cancel_event.is_set() or not heartbeat():
            raise ExecutionRevokedError('Task fragment ownership was revoked')
        if read_workspace(workspace) != before:
            raise ValueError('Native task tools modified controller-owned input files')
        role = micro['role'] if micro else 'implementation'
        declared = (micro or {}).get('deliverables') or [d['name'] for d in output['deliverables']]
        desc = dict(role=role, deliverables=declared)
        if project and micro is None:
            # A simple coding task may return implementation and NEW tests.
            proposed = {}
            for item in output['deliverables']:
                item_role = 'final_test' if within(item['name'], project.test_paths) else 'implementation'
                proposed.update(validate_fragment_deliverables(dict(role=item_role, deliverables=[item['name']]), [item], project=project))
        else:
            proposed = validate_fragment_deliverables(desc, output['deliverables'], project=project)
        if set(conflicts) - proposed.keys():
            raise ValueError('Assembly must explicitly resolve every conflicting file')
        if project and any(within(path, project.test_paths) and path in baseline and baseline[path] != data
                           for path, data in proposed.items()):
            raise ValueError('Task execution cannot modify existing protected tests')
        after = {path: data for path, data in before.items() if not path.startswith('conflicts_428/')}
        after.update(proposed)
        from .coding_checks import validate_generated_files
        validate_generated_files(after, list(proposed))
        # Stage the proposal in a second fresh directory and observe its bytes.
        result_root = descriptor.root / 'task-result'
        result_root.mkdir()
        materialize(result_root, after)
        observed = read_workspace(result_root)
        if observed != after:
            raise ValueError('Task proposal failed physical staging verification')
        with self.store._write() as conn:
            fresh = self.store._get(conn, node['job_id'])
            if not self.store._owned(fresh, node['attempt_id'], node['fencing_token']):
                raise ExecutionRevokedError('Task attempt expired before staged evidence was saved')
            sha = self.store._snapshot(conn, observed)
            evidence = dict(schema='cochem-task-staging/4.2.8', input_sha256=staged['assembly_input_sha256'],
                            source_snapshot_sha256=sha, observed_manifest=manifest(observed),
                            proposed_paths=sorted(proposed), output_sha256=digest(output))
            conn.execute('INSERT INTO task428_fragment_attempts VALUES(?,?,?,?,?,?,?,?,?)',
                (node['job_id'], node['attempt_id'], node['fencing_token'], intent['task_id'],
                 intent.get('microtask_id'), intent.get('plan_generation_sha256'), digest(output), sha,
                 json.dumps(evidence, sort_keys=True)))
        return output, receipt

    def ensure_verification(self, job, requirements):
        accepted = self.accepted_snapshot(job)
        intent = job['payload']['planning_intent']
        capture = self._capture(intent['task_id'])
        files = self.store.coding_files(accepted['snapshot_sha256'])
        base = dict(schema='cochem-task-verification/4.2.8', task_id=intent['task_id'],
                    microtask_id=intent.get('microtask_id'), producer_job_id=job['job_id'],
                    source_modes=capture['modes'], source_snapshot_sha256=accepted['snapshot_sha256'],
                    producer_output_sha256=digest(job['output']), requirements=sorted(set(requirements)))
        phases = [('integrity', files)]
        if capture['project'] is not None:
            project = CodingProject.from_dict(capture['project_id'], capture['project'])
            baseline = self.store.coding_files(capture['snapshot_sha256'])
            test_paths = [p for p in files if within(p, project.test_paths) and p not in baseline]
            names = requirement_test_names(requirements)
            identities = bind_test_identities(files, test_paths, [{'name': name} for name in names.values()])
            base.update(mode='coding_tests', docker=self.runtime.config.docker.as_dict(),
                        expected_test_identities=identities, requirement_test_names=names)
            red = dict(baseline)
            red.update({p: files[p] for p in test_paths})
            phases = [('red', red), ('green', files)]
        else:
            base['mode'] = 'artifact_integrity'
        prerequisite = None
        for phase, phase_files in phases:
            with self.store._write() as conn:
                payload = {**base, 'test_phase': phase, 'prerequisite_job_id': prerequisite,
                           'source_snapshot_sha256': self.store._snapshot(conn, phase_files)}
                key = digest(payload)
                payload['verification_key'] = key
                root_id, job_id = 'verify428-' + key[:40], 'verify428-node-' + key[:40]
                old = conn.execute('SELECT 1 FROM pipeline_jobs WHERE job_id=?', (job_id,)).fetchone()
                if old is None:
                    self.store._insert(conn, root_id, root_id, None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS',
                                       {'workflow_type': 'task_verification428', 'task_id': intent['task_id']})
                    self.store._insert(conn, job_id, root_id, root_id,
                                       'TASK_TEST' if phase != 'integrity' else 'TASK_VERIFY', 'PENDING', payload)
                verified = self.store._get(conn, job_id)
            if verified['status'] != 'COMPLETED':
                return dict(status='TASK_VERIFICATION_HELD' if verified['status'] in ('FAILED', 'BLOCKED')
                            else 'WAITING_FOR_PHYSICAL_VERIFICATION', job_id=job_id)
            if verified['output'].get('passed') is not True:
                return dict(status='TASK_VERIFICATION_REJECTED', job_id=job_id)
            prerequisite = job_id
        return dict(status='VERIFIED', job_id=job_id, output=verified['output'],
                    source_snapshot_sha256=accepted['snapshot_sha256'],
                    integration_status='REVIEW_REQUIRED' if capture['project'] is not None else 'NOT_APPLICABLE')

    def run_verification(self, node, slot, heartbeat, cancel_event, *, container_reservation=None):
        from .container_policy import DockerPolicy
        from .containers import DockerRunner
        from .worker import ExecutionRevokedError, WorkerCleanupError
        payload = node['payload']
        files = self.store.coding_files(payload['source_snapshot_sha256'])
        descriptor = self.runtime.ramdisk.workspace(slot)
        descriptor.validate(identity=descriptor.identity)
        workspace = descriptor.root / 'verify-task'
        workspace.mkdir()
        materialize(workspace, files, payload.get('source_modes'))
        observed = read_workspace(workspace)
        if observed != files:
            raise ValueError('Verification staging changed its immutable input')
        stopped = threading.Event()
        def renew():
            while not stopped.wait(max(.1, min(5, self.runtime.config.lease_seconds / 3))):
                if not heartbeat():
                    cancel_event.set()
                    return
        monitor = threading.Thread(target=renew, daemon=True)
        monitor.start()
        try:
            if cancel_event.is_set() or not heartbeat():
                raise ExecutionRevokedError('Verification ownership revoked')
            if node['kind'] == 'TASK_TEST':
                captured = DockerPolicy.from_dict(payload['docker'])
                current = self.runtime.config.docker
                if (captured.image not in current.allowed_images or captured.endpoint != current.endpoint
                        or captured.executable != current.executable or any(getattr(captured, k) > getattr(current, k)
                        for k in ('memory_mb', 'cpus', 'pids_limit', 'tmpfs_mb', 'max_containers'))):
                    raise ValueError('Captured test policy exceeds current protected bounds')
                runner = DockerRunner(captured, self.runtime.config.private_root / 'containers',
                    trusted_operator=self.runtime.config.operator_name, host_boot_id=self.runtime.boot_id)
                evidence = runner.run(workspace, job_id=node['job_id'], attempt_id=node['attempt_id'],
                    cancel_event=cancel_event, ramdisk_workspace=descriptor, source_modes=payload.get('source_modes'),
                    reservation=container_reservation)
                if evidence.get('cleanup_verified') is not True:
                    raise WorkerCleanupError('Task test container cleanup was not verified')
            else:
                evidence = dict(kind='artifact-integrity', observed_manifest=manifest(observed), cleanup_verified=True,
                                job_id=node['job_id'], attempt_id=node['attempt_id'])
            evidence.update(fencing_token=node['fencing_token'], verification_key=payload['verification_key'],
                            source_snapshot_sha256=payload['source_snapshot_sha256'])
            output = (verify_task_test_evidence(payload, evidence, files) if node['kind'] == 'TASK_TEST'
                      else verify_artifact_evidence(payload, evidence, files))
            if cancel_event.is_set() or not heartbeat():
                raise ExecutionRevokedError('Verification ownership revoked before publication')
            self.store.record_coding_attempt_evidence(node, evidence)
            receipt = dict(executor='task_verifier', job_id=node['job_id'], attempt_id=node['attempt_id'],
                           fencing_token=node['fencing_token'], output_sha256=digest(output), finished_at=time.time())
            return output, receipt, evidence
        finally:
            stopped.set()
            monitor.join(timeout=2)
