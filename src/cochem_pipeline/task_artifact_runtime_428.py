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
from .workflow_428 import _id


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
                CREATE TABLE IF NOT EXISTS task428_cancelled_tasks(
                    task_id TEXT PRIMARY KEY, reason TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS task428_cancelled_no_update BEFORE UPDATE ON task428_cancelled_tasks
                BEGIN SELECT RAISE(ABORT,'task cancellation is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_cancelled_no_delete BEFORE DELETE ON task428_cancelled_tasks
                BEGIN SELECT RAISE(ABORT,'task cancellation is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_source_no_update BEFORE UPDATE ON task428_source_captures
                BEGIN SELECT RAISE(ABORT,'task source capture is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_source_no_delete BEFORE DELETE ON task428_source_captures
                BEGIN SELECT RAISE(ABORT,'task source capture is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_fragment_no_update BEFORE UPDATE ON task428_fragment_attempts
                BEGIN SELECT RAISE(ABORT,'task fragment evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task428_fragment_no_delete BEFORE DELETE ON task428_fragment_attempts
                BEGIN SELECT RAISE(ABORT,'task fragment evidence is immutable'); END;
            ''')
            from .fracture_artifacts_428 import initialize
            initialize(conn)

    def fracture_join(self, task_id, failed_node, fracture_record, completed_children):
        from .fracture_artifacts_428 import join
        return join(self, task_id, failed_node, fracture_record, completed_children)

    def cancel_task(self, task_id):
        """Fence verification roots durably without terminating any process.

        The tombstone and new-verifier insertion use the same database lock.
        An interruption leaves a retryable controller cancellation obligation,
        while the tombstone already prevents additional verification dispatch.
        """
        _id(task_id)
        with self.store._write() as conn:
            conn.execute('INSERT OR IGNORE INTO task428_cancelled_tasks VALUES(?,?)',
                         (task_id, 'Cancelled by operator'))
            roots = [row[0] for row in conn.execute(
                "SELECT job_id FROM pipeline_jobs WHERE kind='MACRO_PLANNING_REQUEST' "
                "AND json_extract(payload_json,'$.workflow_type') IN ('task_verification428','task_delivery428') "
                "AND json_extract(payload_json,'$.task_id')=? ORDER BY job_id", (task_id,))]
        for root in roots:
            self.store.cancel_workflow(root)
        return dict(status='TASK_VERIFICATION_CANCELLED', task_id=task_id)

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

    def _accepted_dependency(self, intent, dep, output):
        if output.get('fracture_join_id'):
            from .fracture_artifacts_428 import resolve
            return resolve(self, intent, dep, output)
        with self.store._connection() as conn:
            rows = conn.execute('''SELECT j.job_id,j.attempt_id,j.fencing_token FROM task428_fragment_attempts a
                JOIN pipeline_jobs j ON j.job_id=a.job_id AND j.attempt_id=a.attempt_id
                AND j.fencing_token=a.fencing_token WHERE a.task_id=? AND a.microtask_id=?
                AND a.generation=? AND j.status='COMPLETED' ''',
                (intent['task_id'], dep, intent['plan_generation_sha256'])).fetchall()
        if output.get('producer_job_id'):
            rows = [row for row in rows if all(row[key] == output.get('producer_' + key)
                    for key in ('job_id', 'attempt_id', 'fencing_token'))]
        if len(rows) != 1:
            raise ValueError('Assigned predecessor lacks one accepted physical snapshot')
        prior = self.store.get(rows[0]['job_id'])
        from .microtask_board_428 import validate_microtask_execution_output
        committed = validate_microtask_execution_output(prior['payload']['microtask_node'], prior['output'])
        if (any(committed.get(key) != output.get(key) for key in
                ('artifact_text', 'deliverables', 'requirement_evidence', 'release_criteria_results'))
                or output.get('artifact_sha256') != committed['artifact_sha256']):
            raise ValueError('Predecessor commitment changed')
        self.accepted_snapshot(prior)
        return prior

    def _dependency_ancestors(self, node, *, cache, visiting=None):
        """Exact completed producer ancestry, never narrative artifact hashes."""
        job_id = node['job_id']
        if job_id in cache:
            return cache[job_id]
        visiting = set(visiting or ())
        if job_id in visiting or len(visiting) >= 64 or len(cache) >= 512:
            raise ValueError('Artifact dependency ancestry exceeds its acyclic bound')
        visiting.add(job_id)
        payload, ancestors = node['payload'], set()
        for dep, output in payload.get('predecessor_outputs', {}).items():
            parent = self._accepted_dependency(payload['planning_intent'], dep, output)
            ancestors.add(parent['job_id'])
            ancestors.update(self._dependency_ancestors(parent, cache=cache, visiting=visiting))
        cache[job_id] = ancestors
        return ancestors

    def _inputs(self, node):
        payload, intent = node['payload'], node['payload']['planning_intent']
        capture = self._capture(intent['task_id'])
        project = (CodingProject.from_dict(capture['project_id'], capture['project'])
                   if capture['project'] is not None else None)
        baseline = self.store.coding_files(capture['snapshot_sha256'])
        before, writers, conflicts = dict(baseline), {}, []
        sealed_tests = {}
        predecessors = payload.get('predecessor_outputs', {})
        if intent['stage'] == 'MICROTASK_EXECUTION':
            declared = set(payload['microtask_node'].get('depends_on', []))
            committed = {dep: output.get('artifact_sha256') for dep, output in predecessors.items()}
            if (set(predecessors) != declared or committed != intent.get('predecessor_artifact_hashes', {})
                    or committed != payload.get('predecessor_artifact_hashes', {})):
                raise ValueError('Task workspace requires exactly its assigned predecessor commitments')
        prior_nodes, ancestry = {}, {}
        for dep, output in sorted(predecessors.items()):
            prior = self._accepted_dependency(intent, dep, output)
            prior_nodes[dep] = prior
            inherited = self.store.coding_files(self.accepted_snapshot(prior)['snapshot_sha256'])
            for path, data in inherited.items():
                if baseline.get(path) != data:
                    writers.setdefault(path, []).append((dep, data))
        for path, versions in writers.items():
            if len({data for _, data in versions}) == 1:
                before[path] = versions[0][1]
            else:
                # An assembly proposal may intentionally replace its exact
                # implementation ancestors. Siblings still require assembly;
                # list order or a newer timestamp never chooses a winner.
                winners = [(dep, data) for dep, data in versions
                    if (prior_nodes[dep]['payload']['microtask_node']['role'] == 'assembly'
                        or predecessors[dep].get('fracture_join_id'))
                    and all(other == dep or prior_nodes[other]['job_id'] in
                            self._dependency_ancestors(prior_nodes[dep], cache=ancestry)
                            for other, _ in versions)]
                if len(winners) == 1:
                    before[path] = winners[0][1]
                    continue
                if payload.get('microtask_node', {}).get('role') != 'assembly':
                    raise ValueError('Conflicting source fragments require explicit assembly')
                conflicts.append(path)
                for dep, data in versions:
                    before['conflicts_428/' + dep + '/' + path] = data
        recovery = payload.get('microtask_node', {}).get('physical_retry')
        simple_retry = intent.get('physical_retry') if intent['stage'] == 'SIMPLE_EXECUTION' else None
        if simple_retry:
            prior = self.store.get(simple_retry['producer_job_id'])
            prior_intent = prior['payload']['planning_intent']
            proof = self.verification_outcome(prior)
            if (prior_intent['task_id'] != intent['task_id'] or prior_intent['stage'] != 'SIMPLE_EXECUTION'
                    or proof['status'] != 'REJECTED' or proof['failure'] != simple_retry['failure']
                    or proof['verification_job_id'] != simple_retry['verification_job_id']):
                raise ValueError('Simple retry requires the exact rejected producer proof')
            before = self.store.coding_files(self.accepted_snapshot(prior)['snapshot_sha256'])
            if project and proof['failure'].get('test_phase') == 'green':
                sealed_tests.update({p: data for p, data in before.items() if within(p, project.test_paths)})
        if recovery:
            if (recovery.get('schema') != 'cochem-microtask-physical-recovery/4.2.8'
                    or not isinstance(recovery.get('sealed_test_producer_ids'), list)
                    or len(recovery['sealed_test_producer_ids']) > 64
                    or len(set(recovery['sealed_test_producer_ids'])) != len(recovery['sealed_test_producer_ids'])):
                raise ValueError('Physical recovery needs bounded exact producer identities')
            checks = {item['producer_job_id']: item for item in recovery['failed_checks']}
            for producer_id in recovery['sealed_test_producer_ids']:
                prior = self.store.get(producer_id)
                prior_intent = prior['payload']['planning_intent']
                proof = self.verification_outcome(prior)
                check = checks.get(producer_id, {})
                if (prior_intent['task_id'] != intent['task_id']
                        or prior_intent.get('plan_generation_sha256') != intent['plan_generation_sha256']
                        or prior['payload'].get('microtask_node', {}).get('role') != 'final_test'
                        or proof['status'] != 'REJECTED' or proof['failure'] != check.get('failure')
                        or proof['verification_job_id'] != check.get('verification_job_id')
                        or not (proof['failure'].get('test_phase') == 'green'
                                or proof['failure'].get('category') == 'content_review')):
                    raise ValueError('Recovery test custody requires the exact rejected final producer')
                if project:
                    inherited = self.store.coding_files(self.accepted_snapshot(prior)['snapshot_sha256'])
                    for path, data in inherited.items():
                        if within(path, project.test_paths):
                            if path in sealed_tests and sealed_tests[path] != data:
                                raise ValueError('Recovery has conflicting sealed tests')
                            sealed_tests[path] = data
            for path, data in sealed_tests.items():
                if path in before and before[path] != data:
                    raise ValueError('Recovery cannot overwrite a sealed requirement test')
                before[path] = data
        validate_project_files(before)
        packet = dict(schema='cochem-task-artifact-staging/4.2.8', workspace_files=before,
                      workspace_manifest=manifest(before), assembly_input_sha256=digest(manifest(before)),
                      sealed_test_paths=sorted(sealed_tests))
        return capture, project, baseline, before, conflicts, packet

    def execution_context(self, payload):
        _, project, _, before, conflicts, packet = self._inputs({'payload': payload})
        intent, micro = payload['planning_intent'], payload.get('microtask_node')
        reqs = micro['requirement_ids'] if micro else [r['id'] for r in intent['task']['document']['requirements']]
        extra = self.planning_context(intent['task_id'])
        if project:
            extra.update(source=source_context(before, {'active_leaf': {'file_targets': (micro or {}).get('deliverables', [])}}, project),
                         required_test_functions=requirement_test_names(reqs),
                         test_rule='Final-test nodes must provide new Python tests with these exact function names, '
                         'real assertions that fail on the original baseline and pass on assembled code. Never edit existing tests.')
        extra['conflicting_paths'] = conflicts
        extra['sealed_test_paths'] = packet['sealed_test_paths']
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
        protected_tests = {**baseline, **{p: before[p] for p in packet['sealed_test_paths']}}
        if project and any(within(path, project.test_paths) and path in protected_tests and protected_tests[path] != data
                           for path, data in proposed.items()):
            raise ValueError('Task execution cannot modify existing protected tests')
        after = {path: data for path, data in before.items() if not path.startswith('conflicts_428/')}
        after.update(proposed)
        from .coding_checks import validate_generated_files
        validate_generated_files(after, list(proposed))
        if project is not None and self.requires_terminal_verification(node['payload']):
            reqs = micro['requirement_ids'] if micro else [r['id'] for r in intent['task']['document']['requirements']]
            test_paths = [p for p in after if within(p, project.test_paths) and p not in baseline]
            # Invalid test definitions are a producer semantic failure while
            # its original native fence is still current, not an unrepairable
            # controller hold after the proposal was marked completed.
            bind_test_identities(after, test_paths,
                                 [{'name': name} for name in requirement_test_names(reqs).values()])
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
        # Never combine a fresh accepted snapshot with a caller's stale intent
        # or proposal; all verification identities derive from the stored winner.
        job = self.store.get(job['job_id'])
        accepted = self.accepted_snapshot(job)
        intent = job['payload']['planning_intent']
        declared = (job['payload']['microtask_node']['requirement_ids']
                    if intent['stage'] == 'MICROTASK_EXECUTION'
                    else [item['id'] for item in intent['task']['document']['requirements']])
        if (not isinstance(requirements, (list, tuple)) or not declared
                or len(requirements) != len(set(requirements)) or set(requirements) != set(declared)):
            raise ValueError('Physical verification must cover the exact immutable producer requirement set')
        requirements = sorted(set(declared))
        capture = self._capture(intent['task_id'])
        files = self.store.coding_files(accepted['snapshot_sha256'])
        base = dict(schema='cochem-task-verification/4.2.8', task_id=intent['task_id'],
                    microtask_id=intent.get('microtask_id'), producer_job_id=job['job_id'],
                    producer_attempt_id=job['attempt_id'], producer_fencing_token=job['fencing_token'],
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
                if conn.execute('SELECT 1 FROM task428_cancelled_tasks WHERE task_id=?',
                                (intent['task_id'],)).fetchone():
                    return dict(status='TASK_VERIFICATION_CANCELLED', task_id=intent['task_id'])
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

    @staticmethod
    def requires_terminal_verification(payload):
        stage = (payload.get('planning_intent') or {}).get('stage')
        return (stage == 'SIMPLE_EXECUTION' or (stage == 'MICROTASK_EXECUTION'
                and (payload.get('microtask_node') or {}).get('role') == 'final_test'))

    def _committed_verification(self, job_id):
        """Read only a fully committed controller observation and its custody.

        The result is a compact binding, never raw provider text, raw command
        output, or a caller's assertion that tests passed.
        """
        with self.store._connection() as conn:
            check = self.store._get(conn, job_id)
            if check['kind'] not in ('TASK_TEST', 'TASK_VERIFY') or check['status'] != 'COMPLETED':
                raise ValueError('Physical outcome requires a committed verifier')
            payload, output, receipt = check['payload'], check['output'], check['receipt']
            stored = conn.execute('SELECT evidence_json,sha256 FROM coding_evidence WHERE job_id=?', (job_id,)).fetchone()
            attempt = conn.execute('SELECT evidence_json,sha256 FROM coding_attempt_evidence '
                'WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                (job_id, check['attempt_id'], check['fencing_token'])).fetchone()
            cleanup = conn.execute('SELECT cleared_at FROM pipeline_execution_cleanup '
                'WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                (job_id, check['attempt_id'], check['fencing_token'])).fetchone()
            if (stored is None or attempt is None or tuple(stored) != tuple(attempt)
                    or cleanup is None or cleanup[0] is None):
                raise ValueError('Physical outcome is missing durable cleaned-up evidence')
            evidence = json.loads(stored['evidence_json'])
            if (payload['verification_key'] != digest({k: v for k, v in payload.items() if k != 'verification_key'})
                    or stored['sha256'] != digest(evidence) or receipt.get('executor') != 'task_verifier'
                    or receipt.get('output_sha256') != digest(output) or receipt.get('cleanup_verified') is not True
                    or any(record.get(key) != check[key] for record in (receipt, evidence)
                           for key in ('job_id', 'attempt_id', 'fencing_token'))
                    or any(evidence.get(key) != payload[key]
                           for key in ('verification_key', 'source_snapshot_sha256'))):
                raise ValueError('Committed verification identities changed')
            producer = self.store._get(conn, payload['producer_job_id'])
            if (any(payload.get('producer_' + key) != producer[key] for key in ('attempt_id', 'fencing_token'))
                    or payload['producer_output_sha256'] != digest(producer['output'])
                    or payload['task_id'] != producer['payload']['planning_intent']['task_id']
                    or payload.get('microtask_id') != producer['payload']['planning_intent'].get('microtask_id')):
                raise ValueError('Physical outcome producer identity changed')
            files = self.store._coding_files(conn, payload['source_snapshot_sha256'])
            validate = verify_task_test_evidence if check['kind'] == 'TASK_TEST' else verify_artifact_evidence
            if output != validate(payload, evidence, files):
                raise ValueError('Committed physical result differs from its exact evidence')
        accepted = self.accepted_snapshot(producer)
        intent = producer['payload']['planning_intent']
        lineage = (producer['payload'].get('microtask_node') or {}).get('attempt_lineage_id', intent['task_id'])
        result = dict(status=output['status'], passed=output['passed'],
            producer_job_id=producer['job_id'], producer_attempt_id=producer['attempt_id'],
            producer_fencing_token=producer['fencing_token'], producer_output_sha256=digest(producer['output']),
            producer_snapshot_sha256=accepted['snapshot_sha256'], verification_job_id=job_id,
            verification_attempt_id=check['attempt_id'], verification_fencing_token=check['fencing_token'],
            verification_output_sha256=digest(output), verification_key=payload['verification_key'],
            source_snapshot_sha256=payload['source_snapshot_sha256'], evidence_sha256=stored['sha256'],
            test_phase=payload['test_phase'], verification_kind=output['verification_kind'], lineage_root=_id(lineage))
        if output['status'] == 'REJECTED':
            expected = set((payload.get('requirement_test_names') or {}).values())
            tests = sorted({(case.get('name', '').split('[', 1)[0], case.get('status'))
                for command in evidence.get('commands', []) for case in command.get('junit_cases', [])
                if case.get('name', '').split('[', 1)[0] in expected
                and case.get('status') in ('passed', 'failed', 'skipped', 'error')})
            category = evidence.get('failure_category')
            result['failure'] = dict(schema='cochem-task-verification-feedback/4.2.8',
                category='physical_verification', test_phase=payload['test_phase'],
                reason=('BASELINE_ASSERTION_NOT_PROVEN' if payload['test_phase'] == 'red'
                        else 'REQUIREMENT_TESTS_NOT_PASSED'),
                execution_category=category if category in ('tests_failed', 'timeout', 'oom', 'output_limit') else None,
                tests=[dict(name=name, status=status) for name, status in tests[:40]],
                tests_truncated=len(tests) > 40, evidence_sha256=stored['sha256'],
                source_snapshot_sha256=payload['source_snapshot_sha256'])
        return result

    def verification_outcome(self, job):
        job = self.store.get(job['job_id'])
        intent = job['payload']['planning_intent']
        requirements = ((job['payload'].get('microtask_node') or {}).get('requirement_ids')
                        or [item['id'] for item in intent['task']['document']['requirements']])
        result = self.ensure_verification(job, requirements)
        if result['status'] in ('VERIFIED', 'TASK_VERIFICATION_REJECTED'):
            proof = self._committed_verification(result['job_id'])
            if proof['verification_kind'] == 'artifact_integrity':
                if intent['stage'] == 'SIMPLE_EXECUTION' and intent['complexity'] <= 3:
                    # The owner's low-tier single-model path completes captured
                    # content with explicit integrity-only scope.
                    return dict(proof, verification_scope='content_integrity')
                from .content_review_428 import ContentReviewRuntime
                review = ContentReviewRuntime.committed_result(self.store, job['job_id'])
                if review is None:
                    return dict(status='WAITING_FOR_INDEPENDENT_CONTENT_VERIFICATION', physical_verification=proof)
                if (review['producer_job_id'] != job['job_id']
                        or review['producer_output_sha256'] != proof['producer_output_sha256']
                        or review['physical_job_id'] != proof['verification_job_id']
                        or review['source_snapshot_sha256'] != proof['source_snapshot_sha256']):
                    raise ValueError('Content review does not bind the physical producer result')
                proof.update(status='VERIFIED' if review['accepted'] else 'REJECTED', passed=review['accepted'],
                    verification_scope='content_integrity_and_independent_model_review',
                    content_review=dict(job_id=review['review_job_id'], output_sha256=review['review_output_sha256'],
                                        binding_sha256=review['binding_sha256']))
                if not review['accepted']:
                    proof['failure'] = dict(schema='cochem-task-verification-feedback/4.2.8',
                        category='content_review', reason='REQUIREMENTS_NOT_SATISFIED',
                        findings=[item[:2000] for item in review['findings'][:20]],
                        findings_truncated=len(review['findings']) > 20,
                        requirements=[dict(requirement_id=item['requirement_id'], satisfied=item['satisfied'],
                                           assessment=item['assessment'][:1000]) for item in review['assessments'][:40]],
                        requirements_truncated=len(review['assessments']) > 40,
                        review_output_sha256=review['review_output_sha256'],
                        source_snapshot_sha256=proof['source_snapshot_sha256'])
            return proof
        return result

    def retry_feedback(self, task_id, microtask_id=None):
        """Return deterministic retry input from rejected producer attempts only.

        Polling never changes generation, and a verifier re-run cannot create a
        second generation for the same original producer fence. The caller must
        still reconcile its attempt ledger and honor research/pivot boundaries.
        """
        _id(task_id)
        if microtask_id is not None:
            _id(microtask_id)
        with self.store._connection() as conn:
            if conn.execute('SELECT 1 FROM task428_cancelled_tasks WHERE task_id=?', (task_id,)).fetchone():
                return None
            sql = ("SELECT j.job_id AS observed_job_id,0 AS content,o.created_at AS observed_at "
                "FROM pipeline_jobs j JOIN pipeline_outputs o USING(job_id) "
                "WHERE j.kind IN ('TASK_TEST','TASK_VERIFY') AND j.status='COMPLETED' "
                "AND json_extract(j.payload_json,'$.task_id')=? "
                "AND json_extract(j.payload_json,'$.microtask_id') IS ? "
                "AND json_extract(o.output_json,'$.status')='REJECTED' ")
            params = [task_id, microtask_id]
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='task428_content_review_results'").fetchone():
                sql += ("UNION ALL SELECT j.job_id AS observed_job_id,1 AS content,o.created_at AS observed_at "
                    "FROM task428_content_review_results r "
                    'JOIN pipeline_jobs j ON j.job_id=r.producer_job_id '
                    'JOIN pipeline_outputs o ON o.job_id=r.review_job_id '
                    "WHERE json_extract(j.payload_json,'$.planning_intent.task_id')=? "
                    "AND json_extract(j.payload_json,'$.planning_intent.microtask_id') IS ? "
                    "AND json_extract(r.verdict_json,'$.accepted')=0 ")
                params += [task_id, microtask_id]
            rows = list(conn.execute(sql + 'ORDER BY observed_at,observed_job_id LIMIT 129', params))
        if len(rows) > 128:
            raise ValueError('Verification history exceeds bounded lineage reconciliation')
        rejected = {}
        for row in rows:
            result = (self.verification_outcome({'job_id': row['observed_job_id']}) if row['content']
                      else self._committed_verification(row['observed_job_id']))
            if result['status'] != 'REJECTED':
                continue
            key = (result['producer_job_id'], result['producer_attempt_id'], result['producer_fencing_token'])
            rejected.setdefault(key, result)
        if not rejected:
            return None
        # The first rejection of an original producer fence is authoritative;
        # a duplicate verifier observation cannot rewrite existing retry input.
        latest = list(rejected.values())[-1]
        return dict(retry_generation=len(rejected), producer_job_id=latest['producer_job_id'],
                    verification_job_id=latest['verification_job_id'], failure=latest['failure'],
                    lineage_root=latest['lineage_root'])

    def run_verification(self, node, slot, heartbeat, cancel_event, *, container_reservation=None):
        from .container_policy import DockerPolicy
        from .containers import DockerRunner, ContainerCapacityError, ContainerCleanupError
        from .worker import ExecutionRevokedError, WorkerCleanupError, ProviderFailure
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
                try:
                    evidence = runner.run(workspace, job_id=node['job_id'], attempt_id=node['attempt_id'],
                        cancel_event=cancel_event, ramdisk_workspace=descriptor, source_modes=payload.get('source_modes'),
                        reservation=container_reservation)
                except ContainerCleanupError as exc:
                    raise WorkerCleanupError('Task test container cleanup was not verified') from exc
                except ContainerCapacityError as exc:
                    raise ProviderFailure('resource', retry_after_seconds=5) from exc
            else:
                evidence = dict(kind='artifact-integrity', observed_manifest=manifest(observed), cleanup_verified=True,
                                job_id=node['job_id'], attempt_id=node['attempt_id'])
            evidence.update(fencing_token=node['fencing_token'], verification_key=payload['verification_key'],
                            source_snapshot_sha256=payload['source_snapshot_sha256'])
            # Preserve the observed physical attempt even when its lease was
            # revoked or its proof is inadequate. Publication still fails below.
            self.store.record_coding_attempt_evidence(node, evidence)
            if evidence.get('cleanup_verified') is not True:
                raise WorkerCleanupError('Task test container cleanup was not verified')
            if cancel_event.is_set() or not heartbeat() or evidence.get('failure_category') == 'cancelled':
                raise ExecutionRevokedError('Verification ownership revoked before publication')
            candidate_failure = evidence.get('failure_category') in ('oom', 'timeout', 'output_limit')
            source_proven = evidence.get('source_verified') is True or evidence.get('input_source_verified') is True
            if evidence.get('failure_category') == 'container_contract' and source_proven:
                raise ProviderFailure('configuration')
            if evidence.get('quarantine_required') and not (candidate_failure and source_proven):
                raise ProviderFailure('resource', retry_after_seconds=30)
            if node['kind'] == 'TASK_TEST' and not evidence.get('passed') and evidence.get('failure_category') != 'tests_failed' and not (candidate_failure and source_proven):
                raise ProviderFailure('resource', retry_after_seconds=30)
            output = (verify_task_test_evidence(payload, evidence, files) if node['kind'] == 'TASK_TEST'
                      else verify_artifact_evidence(payload, evidence, files))
            if cancel_event.is_set() or not heartbeat():
                raise ExecutionRevokedError('Verification ownership revoked before publication')
            receipt = dict(executor='task_verifier', job_id=node['job_id'], attempt_id=node['attempt_id'],
                           fencing_token=node['fencing_token'], output_sha256=digest(output),
                           cleanup_verified=True, finished_at=time.time())
            return output, receipt, evidence
        finally:
            stopped.set()
            monitor.join(timeout=2)
