"""Independent durable repair queue and completion-audit sampling policy.

This controller library launches nothing. An out-of-band supervisor consumes
the queue directly and uses dedicated profiles, native acceptance, the shared
host execution limit and quota accounting. Pipeline jobboard health is not a
prerequisite. This does not grant an agent administrator or protected-state access.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time
import uuid

from .task_routing import digest, five_model_options
from .workflow_428 import _id, _sha, _text


def sample_completion(job_id, output_sha256, *, sample_basis_points):
    """Stable sample survives restarts; failures are separately always audited."""
    _id(job_id)
    _sha(output_sha256)
    if type(sample_basis_points) is not int or not 0 <= sample_basis_points <= 10000:
        raise ValueError('Sampling rate must be explicit basis points')
    value = int.from_bytes(hashlib.sha256((job_id+'\0'+output_sha256).encode()).digest()[:8], 'big')
    return value % 10000 < sample_basis_points


def repair_paths(paths):
    """Repository repairs only; no credentials, host controls or policy rewrites."""
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
        raise ValueError('Repair requires a bounded changed-path inventory')
    normalized = []
    for value in paths:
        if (not isinstance(value, str) or '\\' in value or ':' in value or '\x00' in value
                or any(part in ('.','..','') for part in value.split('/'))):
            raise ValueError('Repair path is not a literal relative repository path')
        path = PurePosixPath(value)
        if (path.is_absolute() or path.parts[0] not in ('src','scripts','pipeline_tests','docs')
                or any(part.startswith('.') for part in path.parts)
                or any(part.lower() in ('agents.md','credentials','secrets') for part in path.parts)
                or path.suffix.lower() not in ('.py','.ps1','.md','.json','.toml','.txt')):
            raise ValueError('Repair path is outside the source/test/documentation scope')
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise ValueError('Duplicate repair paths')
    return normalized


class RepairQueue:
    def __init__(self, path, catalog, *, profiles, normal_profile_ids,
                 verify_reservation, verify_commit):
        if str(path) == ':memory:':
            raise ValueError('Repair incidents require a durable independent journal')
        if not isinstance(profiles, dict) or not profiles or len(profiles) > 6:
            raise ValueError('Dedicated repair profiles must be explicitly configured')
        self.profiles = deepcopy(profiles)
        for key, profile in profiles.items():
            _id(key)
            if key in normal_profile_ids or set(profile) != {'provider','quota_pool'}:
                raise ValueError('Repair identities must be separate from normal worker identities')
            if profile['provider'] not in ('codex','claude','gemini'):
                raise ValueError('Unknown repair provider')
            _id(profile['quota_pool'])
        self.catalog = deepcopy(catalog)
        self.verify_reservation, self.verify_commit = verify_reservation, verify_commit
        self.path = Path(path)
        with self._write() as conn:
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS repair428_incidents(
                incident_id TEXT PRIMARY KEY, evidence_sha256 TEXT UNIQUE NOT NULL,
                request_json TEXT NOT NULL, state TEXT NOT NULL,
                lease TEXT UNIQUE, execution_json TEXT, result_json TEXT, created_at REAL NOT NULL);
              CREATE UNIQUE INDEX IF NOT EXISTS repair428_one_active
                ON repair428_incidents((1)) WHERE state='ACTIVE';
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

    def report(self, incident_id, summary, evidence_sha256, *, source_kind, task_types):
        _id(incident_id)
        _text(summary, 'Repair incident', 8000)
        _sha(evidence_sha256)
        if source_kind not in ('controller_fault','completion_spotcheck','native_fault','invariant_failure'):
            raise ValueError('Unrecognized repair incident source')
        options = five_model_options(self.catalog, task_types, 10)
        targets = [x['model_id'] for x in options if x['meets_floor']]
        request = dict(schema='cochem-independent-repair-request/4.2.8', incident_id=incident_id,
            summary=summary, source_kind=source_kind, evidence_sha256=evidence_sha256,
            task_types=task_types, complexity=10, target_profiles=targets,
            captured_catalog_sha256=digest(self.catalog), priority='highest_for_competing_quota',
            repository_changes_authorized=True, administrator_actions_authorized=False,
            normal_jobboard_required=False, automatic_quota_bypass=False)
        with self._write() as conn:
            existing = conn.execute('SELECT request_json FROM repair428_incidents WHERE incident_id=? OR evidence_sha256=?',
                                    (incident_id, evidence_sha256)).fetchone()
            if existing:
                prior = json.loads(existing[0])
                if prior != request:
                    raise ValueError('Repair evidence already belongs to an immutable incident')
                return prior
            conn.execute('INSERT INTO repair428_incidents VALUES(?,?,?,?,NULL,NULL,NULL,?)',
                (incident_id, evidence_sha256, json.dumps(request), 'QUEUED', time.time()))
        return request

    def priority_waiting(self, quota_pool):
        """A waiting repair goes before new ordinary work in a competing pool.

        Existing leases are never preempted. A lower-tier substitute is never
        used to get around exhaustion of a tier-10 model's quota.
        """
        _id(quota_pool)
        with self._write() as conn:
            queued = [json.loads(row[0]) for row in conn.execute(
                "SELECT request_json FROM repair428_incidents WHERE state IN ('QUEUED','WAITING_QUOTA')")]
        for request in queued:
            providers = {self.catalog['models'][key]['provider'] for key in request['target_profiles']}
            if any(p['provider'] in providers and p['quota_pool'] == quota_pool for p in self.profiles.values()):
                return True
        return False

    def claim(self, incident_id, profile_id, model_id, reservation_id):
        """Caller has already acquired a real shared host-slot/quota reservation."""
        profile = self.profiles.get(profile_id)
        if profile is None:
            raise ValueError('Only a dedicated repair identity can claim')
        if self.verify_reservation is None:
            raise ValueError('Shared host-slot and quota verifier is unavailable')
        proof = self.verify_reservation(reservation_id)
        if (not isinstance(proof, dict) or proof.get('active') is not True
                or proof.get('dedicated_profile') != profile_id or proof.get('model_id') != model_id
                or proof.get('quota_pool') != profile['quota_pool'] or proof.get('purpose') != 'pipeline_repair'
                or proof.get('shared_capacity') != 4 or type(proof.get('shared_capacity')) is not int
                or type(proof.get('slot')) is not int or not 0 <= proof['slot'] < 4
                or proof.get('native_accepted') is not True):
            raise ValueError('Repair lacks an active exact-model shared host/quota reservation')
        model = self.catalog['models'].get(model_id)
        if model is None or model['provider'] != profile['provider']:
            raise ValueError('Repair provider/model identity differs')
        maximum = 'high' if model['provider'] == 'gemini' else 'max'
        if model['effort'] != maximum:
            raise ValueError('Out-of-band repairs require maximum reasoning effort')
        with self._write() as conn:
            row = conn.execute('SELECT * FROM repair428_incidents WHERE incident_id=?', (incident_id,)).fetchone()
            if row is None or row['state'] not in ('QUEUED','WAITING_QUOTA'):
                raise ValueError('Repair is not queued')
            request = json.loads(row['request_json'])
            if request['captured_catalog_sha256'] != digest(self.catalog):
                raise ValueError('Repair must retain its original catalog until explicitly migrated')
            if model_id not in request['target_profiles']:
                raise ValueError('Model does not meet the captured tier-10 task floors')
            lease = uuid.uuid4().hex
            execution = dict(reservation_id=reservation_id, model_id=model_id, profile_id=profile_id,
                             reservation_proof_sha256=digest(proof), lease=lease)
            try:
                conn.execute("UPDATE repair428_incidents SET state='ACTIVE',lease=?,execution_json=? WHERE incident_id=?",
                             (lease, json.dumps(execution), incident_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError('Another repair is active; no parallel repair agent is allowed') from exc
            return request | execution

    def record_commit(self, lease, commit_sha, test_evidence_sha256):
        _sha(test_evidence_sha256)
        if not isinstance(commit_sha, str) or not re.fullmatch('[0-9a-f]{40,64}', commit_sha):
            raise ValueError('Repair result requires a literal Git commit identity')
        if self.verify_commit is None:
            raise ValueError('Independent Git/test verifier is unavailable')
        proof = self.verify_commit(commit_sha, test_evidence_sha256)
        if (not isinstance(proof, dict) or proof.get('commit_sha') != commit_sha
                or proof.get('tests_passed') is not True or proof.get('working_tree_clean') is not True
                or proof.get('cleanup_verified') is not True or proof.get('test_evidence_sha256') != test_evidence_sha256):
            raise ValueError('Repair must have independently verified Git, tests and cleanup evidence')
        repair_paths(proof.get('changed_paths'))
        with self._write() as conn:
            row = conn.execute('SELECT * FROM repair428_incidents WHERE lease=?', (lease,)).fetchone()
            if row is None or row['state'] != 'ACTIVE':
                raise ValueError('Stale or unowned repair completion')
            execution = json.loads(row['execution_json'])
            if proof.get('reservation_id') != execution['reservation_id']:
                raise ValueError('Repair cleanup belongs to a different reservation')
            result = dict(commit_sha=commit_sha, test_evidence_sha256=test_evidence_sha256,
                changed_paths=proof['changed_paths'], evidence_sha256=digest(proof), deployment_performed=False)
            conn.execute("UPDATE repair428_incidents SET state='SOURCE_REPAIRED',result_json=? WHERE lease=?",
                         (json.dumps(result), lease))
            return result

    def get_incident(self, incident_id):
        _id(incident_id)
        with self._write() as conn:
            row = conn.execute(
                'SELECT * FROM repair428_incidents WHERE incident_id=?',
                (incident_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(
            incident_id=row['incident_id'],
            evidence_sha256=row['evidence_sha256'],
            state=row['state'],
            lease=row['lease'],
            request=json.loads(row['request_json']),
            execution=json.loads(row['execution_json']) if row['execution_json'] else None,
            result=json.loads(row['result_json']) if row['result_json'] else None,
            created_at=float(row['created_at']),
        )

    def list_incidents(self, *, state=None):
        with self._write() as conn:
            if state is not None:
                rows = conn.execute(
                    'SELECT incident_id FROM repair428_incidents WHERE state=? ORDER BY created_at ASC, incident_id ASC',
                    (state,),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT incident_id FROM repair428_incidents ORDER BY created_at ASC, incident_id ASC'
                ).fetchall()
        return [self.get_incident(r['incident_id']) for r in rows]

    def mark_waiting_quota(self, incident_id):
        _id(incident_id)
        with self._write() as conn:
            row = conn.execute(
                'SELECT * FROM repair428_incidents WHERE incident_id=?',
                (incident_id,),
            ).fetchone()
            if row is None or row['state'] not in ('QUEUED', 'WAITING_QUOTA'):
                raise ValueError('Incident is not queued for quota wait')
            conn.execute(
                "UPDATE repair428_incidents SET state='WAITING_QUOTA' WHERE incident_id=?",
                (incident_id,),
            )
        return self.get_incident(incident_id)

    def recover_stale_lease(self, lease, *, cleanup_verified, cleanup_receipt_sha256):
        _id(lease)
        _sha(cleanup_receipt_sha256)
        if cleanup_verified is not True:
            raise ValueError('Cannot recover stale repair lease without verified native cleanup')
        with self._write() as conn:
            row = conn.execute(
                'SELECT * FROM repair428_incidents WHERE lease=?',
                (lease,),
            ).fetchone()
            if row is None or row['state'] != 'ACTIVE':
                raise ValueError('Unknown or non-active repair lease')
            inc_id = row['incident_id']
            conn.execute(
                "UPDATE repair428_incidents SET state='QUEUED', lease=NULL, execution_json=NULL WHERE lease=?",
                (lease,),
            )
        return self.get_incident(inc_id)

    def apply_runtime_transition(
        self,
        incident_id,
        *,
        supervisor_authority_verified,
        supervisor_receipt_id=None,
        runtime_version_sha256=None,
        smoke_check_sha256=None,
    ):
        """Transition a `SOURCE_REPAIRED` incident to `RESOLVED` only through reviewed supervisor authority (`P428-21`)."""
        _id(incident_id)
        with self._write() as conn:
            row = conn.execute(
                'SELECT * FROM repair428_incidents WHERE incident_id=?',
                (incident_id,),
            ).fetchone()
            if row is None or row['state'] not in ('SOURCE_REPAIRED', 'AWAITING_SUPERVISOR_TRANSITION'):
                raise ValueError('Incident must be in SOURCE_REPAIRED state before runtime transition')
            result = json.loads(row['result_json']) if row['result_json'] else {}
            if supervisor_authority_verified is not True or not supervisor_receipt_id:
                result.update(
                    deployment_performed=False,
                    supervisor_transition_status='HELD_AWAITING_SUPERVISOR_AUTHORITY',
                )
                conn.execute(
                    "UPDATE repair428_incidents SET state='AWAITING_SUPERVISOR_TRANSITION', result_json=? WHERE incident_id=?",
                    (json.dumps(result, sort_keys=True), incident_id),
                )
            else:
                _id(supervisor_receipt_id)
                _sha(runtime_version_sha256)
                _sha(smoke_check_sha256)
                result.update(
                    deployment_performed=True,
                    supervisor_transition_status='APPLIED_BY_REVIEWED_SUPERVISOR',
                    supervisor_receipt_id=supervisor_receipt_id,
                    runtime_version_sha256=runtime_version_sha256,
                    smoke_check_sha256=smoke_check_sha256,
                )
                conn.execute(
                    "UPDATE repair428_incidents SET state='RESOLVED', result_json=? WHERE incident_id=?",
                    (json.dumps(result, sort_keys=True), incident_id),
                )
        return self.get_incident(incident_id)



