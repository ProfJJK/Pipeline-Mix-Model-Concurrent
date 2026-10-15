"""Read-only legacy inventory and prepared requests, separate from installation.

Original databases are never changed here. Inventory reads hash-pinned SQLite
online backups into memory; payloads stay in the archive, not the report. The
submission ledger records intent before dispatch and never retries an uncertain
POST. A caller must reconcile the deterministic task ID with the controller.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time

from .ramdisk import ordinary_tree

_SHA = re.compile(r'[a-f0-9]{64}\Z')
_ROLES = {'kanban', 'exam_evidence', 'v412', 'youtube', 'layer1'}
_TABLES = {
    'kanban': ('kanban_tasks', 'kanban_tasks_v3', 'project_registry'),
    'exam_evidence': ('jobs',), 'v412': ('jobs',), 'youtube': ('jobs',),
    'layer1': ('layer1_queue',),
}
_KEYS = {'kanban_tasks': 'task_id', 'kanban_tasks_v3': 'task_id',
         'project_registry': 'target_name', 'jobs': 'id', 'layer1_queue': 'request_id'}
_DONE = {'done', 'completed', 'complete', 'success', 'succeeded'}
_DELETE = {'kanban_tasks': {'scout_audit', 'manual_assembly', 'manual_compile', 'library_research', 'srs'},
           'kanban_tasks_v3': {'srs', 'srs_generation'}}
_QUEUE = {'kanban_tasks': {'quick_reference', 'consensus_extract', 'target_evaluation', 'improvement'},
          'kanban_tasks_v3': {'generate_r_exams'}}


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError('Expected a full lowercase SHA256 digest')
    return value


def _pinned_bytes(path, expected_sha256, *, maximum):
    path = Path(path).absolute()
    _sha(expected_sha256)
    ordinary_tree(path)
    before = path.stat()
    if not path.is_file() or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
        raise ValueError('Expected a bounded ordinary single-link file')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    after = path.stat()
    if (len(raw) > maximum or hashlib.sha256(raw).hexdigest() != expected_sha256 or
            (before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError('Pinned input digest changed')
    return raw


def _row_value(value):
    # Preserve bytes exactly in row hashes without leaking their contents.
    if isinstance(value, bytes):
        return {'sqlite_blob_base64': base64.b64encode(value).decode('ascii')}
    return value


def _fixture(row):
    text = _canonical(row).replace('\\\\', '/').replace('\\', '/').lower()
    return 'appdata/local/temp/cochem_test_target_' in text


def _classify(role, table, row):
    category = str(row.get('workflow_type', row.get('job_type', table)))
    status = str(row.get('status', '')).lower()
    if _fixture(row):
        return category, 'EXCLUDE_FIXTURE'
    if status in _DONE:
        return category, 'PRESERVE_COMPLETED'
    if role == 'kanban':
        if table == 'project_registry':
            return 'research_target', 'QUEUE_REVIEW'
        if category in _DELETE.get(table, set()):
            return category, 'DELETE_REVIEW'
        if category in _QUEUE.get(table, set()):
            return category, 'QUEUE_REVIEW'
    if role == 'exam_evidence':
        payload = row.get('payload_json')
        try:
            payload = _json(payload) if isinstance(payload, str) else {}
        except (ValueError, TypeError):
            payload = {}
        if (isinstance(payload, dict) and payload.get('course_id') == 'CHEM311' or
                str(row.get('task_id', '')).startswith('CHEM311_')):
            return 'chem311_testbank', 'QUEUE_REVIEW'
    return category, 'PRESERVE_UNDECIDED'


def inventory_snapshots(manifest_path, manifest_sha256, source_roles, *, maximum_rows=20000, deadline_seconds=30):
    """Inventory explicit source roles from completed, digest-bound backups.

    Roles are supplied by the reviewed source specification, never inferred from
    a filename. Stable row references exclude snapshot hashes, so a later backup
    cannot silently create a second submission identity for the same legacy row.
    """
    if type(maximum_rows) is not int or not 1 <= maximum_rows <= 100000:
        raise ValueError('Invalid row bound')
    if type(deadline_seconds) not in (int, float) or not 1 <= deadline_seconds <= 120:
        raise ValueError('Invalid inventory deadline')
    manifest_path = Path(manifest_path).absolute()
    manifest = _json(_pinned_bytes(manifest_path, manifest_sha256, maximum=1024 * 1024))
    if (manifest.get('schema') != 'cochem-legacy-online-snapshots/1' or
            manifest.get('status') != 'COMPLETE_PER_DATABASE' or
            not isinstance(manifest.get('snapshots'), list) or not 1 <= len(manifest['snapshots']) <= 32):
        raise ValueError('Completed per-database online snapshots are required')
    if not isinstance(source_roles, dict) or any(role not in _ROLES for role in source_roles.values()):
        raise ValueError('Explicit supported source roles are required')
    expected_sources = {item.get('source') for item in manifest['snapshots']}
    if set(source_roles) != expected_sources or len(expected_sources) != len(manifest['snapshots']):
        raise ValueError('Every snapshot must have exactly one explicit source role')
    deadline = time.monotonic() + deadline_seconds
    rows, sources, seen, total_bytes = [], [], set(), 0
    for snapshot in sorted(manifest['snapshots'], key=lambda item: item['source']):
        source, filename = snapshot['source'], snapshot['snapshot']
        if (not isinstance(filename, str) or Path(filename).name != filename or
                '/' in filename or '\\' in filename or filename in {'.', '..'}):
            raise ValueError('Snapshot must be an immediate ordinary file')
        path = manifest_path.parent / filename
        if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('Closed snapshots must not have SQLite sidecars')
        raw = _pinned_bytes(path, snapshot['sha256'], maximum=256 * 1024 * 1024)
        total_bytes += len(raw)
        if total_bytes > 512 * 1024 * 1024 or len(raw) != snapshot['bytes']:
            raise ValueError('Snapshot size bound differs')
        if raw[:16] != b'SQLite format 3\0' or raw[18:20] not in (b'\1\1', b'\2\2'):
            raise ValueError('Unsupported SQLite snapshot header')
        role = source_roles[source]
        source_id = digest({'source': source.replace('\\', '/').casefold(), 'role': role})
        source_info = {'source': source, 'source_id': source_id, 'role': role,
                       'snapshot': filename, 'snapshot_sha256': snapshot['sha256'], 'tables': {}}
        with closing(sqlite3.connect(':memory:')) as db:
            # SQLite's documented in-memory normalization of closed WAL backups.
            db.deserialize(raw[:18] + b'\1\1' + raw[20:] if raw[18:20] == b'\2\2' else raw)
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            if db.execute('PRAGMA quick_check').fetchmany(2) != [('ok',)]:
                raise ValueError('Snapshot integrity verification failed')
            objects = {name: (kind, sql or '') for name, kind, sql in
                       db.execute('SELECT name,type,sql FROM sqlite_schema')}
            for table in _TABLES[role]:
                if table not in objects:
                    continue
                if objects[table][0] != 'table' or 'CREATE VIRTUAL TABLE' in objects[table][1].upper():
                    raise ValueError('Legacy inventory requires physical tables')
                columns = db.execute(f'PRAGMA table_info("{table}")').fetchall()
                names = [c[1] for c in columns]
                key = _KEYS[table]
                if key not in names or 'status' not in names or [c[1] for c in columns if c[5]] != [key]:
                    raise ValueError('Unsupported or ambiguous legacy primary key/schema')
                cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY "{key}"')
                count = 0
                for values in cursor:
                    if time.monotonic() > deadline or len(rows) >= maximum_rows:
                        raise ValueError('Legacy inventory exceeded its time or row bound')
                    row = {name: _row_value(value) for name, value in zip(names, values)}
                    if len(_canonical(row)) > 1024 * 1024:
                        raise ValueError('Legacy row exceeds its payload bound')
                    identity = row[key]
                    if not (type(identity) is int or isinstance(identity, str) and 0 < len(identity) <= 1024):
                        raise ValueError('Invalid legacy primary key')
                    reference = 'legacy:' + digest({'source_id': source_id, 'table': table, 'key': identity})
                    if reference in seen:
                        raise ValueError('Duplicate legacy reference')
                    seen.add(reference)
                    category, disposition = _classify(role, table, row)
                    rows.append({'reference': reference, 'source_id': source_id, 'table': table,
                                 'primary_key_column': key, 'primary_key': identity,
                                 'row_sha256': digest(row), 'snapshot_sha256': snapshot['sha256'],
                                 'category': category, 'status': row['status'], 'disposition': disposition,
                                 'attempts': row.get('attempts', row.get('retry_count')),
                                 'max_attempts': row.get('max_attempts'),
                                 'source_references': {name: row[name] for name in
                                     ('file_path', 'payload_uri', 'current_path') if isinstance(row.get(name), str)
                                     and 0 < len(row[name]) <= 2048},
                                 'payload_sha256': digest({name: row[name] for name in names if name in
                                      {'payload', 'payload_json', 'prompt', 'payload_uri', 'file_path', 'current_path'}})})
                    count += 1
                source_info['tables'][table] = count
        sources.append(source_info)
    rows.sort(key=lambda row: row['reference'])
    return {'schema': 'cochem-legacy-backlog-inventory/1', 'snapshot_manifest_sha256': manifest_sha256,
            'sources': sources, 'rows': rows, 'counts': dict(sorted(Counter(r['disposition'] for r in rows).items())),
            'source_writes': 0, 'controller_writes': 0, 'payloads_published': False}


def _safe_text(value, name, maximum):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= maximum or '\0' in value:
        raise ValueError(f'INVALID_{name}')
    return value.strip()


def _validate_inputs(inputs):
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 100:
        raise ValueError('MISSING_REVIEWED_INPUTS')
    seen, total = set(), 0
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise ValueError('INVALID_INPUT_BINDING')
        path = Path(item['path'])
        if not path.is_absolute() or str(path).casefold() in seen:
            raise ValueError('INVALID_INPUT_PATH')
        seen.add(str(path).casefold())
        try:
            raw = _pinned_bytes(path, item['sha256'], maximum=32 * 1024 * 1024)
        except FileNotFoundError as error:
            raise ValueError('INPUT_MISSING') from error
        except (OSError, ValueError) as error:
            raise ValueError('INPUT_DIGEST_MISMATCH') from error
        total += len(raw)
        if total > 128 * 1024 * 1024:
            raise ValueError('INPUT_SIZE_BOUND_EXCEEDED')


def _prepare(resolution):
    allowed = {'target_key', 'stage', 'objective', 'inputs', 'deliverables', 'history_disposition', 'project_id'}
    if not isinstance(resolution, dict) or set(resolution) - allowed:
        raise ValueError('INVALID_RESOLUTION')
    target = _safe_text(resolution.get('target_key'), 'TARGET_KEY', 512)
    stage = _safe_text(resolution.get('stage'), 'STAGE', 128)
    objective = _safe_text(resolution.get('objective'), 'OBJECTIVE', 16000)
    history = _safe_text(resolution.get('history_disposition'), 'HISTORY_DISPOSITION', 2000)
    _validate_inputs(resolution.get('inputs'))
    deliverables = resolution.get('deliverables')
    if not isinstance(deliverables, list) or not 1 <= len(deliverables) <= 100:
        raise ValueError('MISSING_DELIVERABLE_CHECKS')
    paths = set()
    for artifact in deliverables:
        if not isinstance(artifact, dict) or set(artifact) != {'path', 'checks'}:
            raise ValueError('INVALID_DELIVERABLE_CONTRACT')
        path = _safe_text(artifact.get('path'), 'DELIVERABLE_PATH', 512)
        if (PurePosixPath(path).is_absolute() or '\\' in path or ':' in path or
                any(part in {'..', '.'} for part in path.split('/')) or path.casefold() in paths):
            raise ValueError('INVALID_DELIVERABLE_PATH')
        paths.add(path.casefold())
        checks = artifact.get('checks')
        if not isinstance(checks, list) or not 1 <= len(checks) <= 50:
            raise ValueError('MISSING_DELIVERABLE_CHECKS')
        for check in checks:
            _safe_text(check, 'DELIVERABLE_CHECK', 2000)
    project = resolution.get('project_id')
    if project is not None:
        _safe_text(project, 'PROJECT_ID', 128)
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', project):
            raise ValueError('INVALID_PROJECT_ID')
        if project == 'windows-acceptance':
            raise ValueError('PRODUCTION_FIXTURE_FORBIDDEN')
    identity = {'target_key': target, 'stage': stage, 'project_id': project}
    task_id = 'legacy428-' + digest(identity)
    contract = {'inputs': resolution['inputs'], 'deliverables': deliverables, 'history_disposition': history}
    body = {'task_id': task_id, 'objective': objective + '\n\nInitial handoff and acceptance contract:\n' +
            _canonical(contract) + '\nProduce the actual deliverables. Do not claim success from prose alone. '
            'Missing sources or failed checks must remain explicit holds; preserve historical attempts and budgets.'}
    if project is not None:
        body['project_id'] = project
    # PlanningJournal.create uses workflow_428._text's 16,000 character intake
    # bound. Count the complete injected contract, not only the short objective.
    if len(body['objective']) > 16000:
        raise ValueError('INTAKE_OBJECTIVE_BOUND_EXCEEDED')
    return {'schema': 'cochem-legacy-prepared-request/1', 'endpoint': '/tasks/submit',
            'identity': identity, 'contract': contract, 'body': body}


def validate_prepared_request(request):
    if (not isinstance(request, dict) or set(request) != {'schema', 'endpoint', 'identity', 'contract', 'body'} or
            request['schema'] != 'cochem-legacy-prepared-request/1' or request['endpoint'] != '/tasks/submit'):
        raise ValueError('Invalid prepared request')
    if request['body'].get('task_id') != 'legacy428-' + digest(request['identity']):
        raise ValueError('Prepared task identity differs')
    _validate_inputs(request['contract']['inputs'])
    if set(request['body']) - {'task_id', 'objective', 'project_id'}:
        raise ValueError('Prepared request cannot choose routing or budget authority')
    _safe_text(request['body'].get('objective'), 'OBJECTIVE', 16000)
    if request['body'].get('project_id') == 'windows-acceptance':
        raise ValueError('PRODUCTION_FIXTURE_FORBIDDEN')
    return True


def build_recovery_plan(inventory, resolutions=None):
    """Compile exact deletion/archive candidates and held/prepared queue entries.

    Resolutions supply verified inputs and semantic target/stage identities. This
    deliberately does not guess path remaps, regenerated consensus payloads,
    finished research stages, retries or specialist ownership releases.
    """
    if inventory.get('schema') != 'cochem-legacy-backlog-inventory/1':
        raise ValueError('Expected a verified inventory')
    resolutions = resolutions or {}
    references = {row['reference'] for row in inventory['rows']}
    if not isinstance(resolutions, dict) or set(resolutions) - references:
        raise ValueError('Resolution references must match the pinned inventory')
    deletion, queue = [], []
    for row in inventory['rows']:
        if row['disposition'] == 'DELETE_REVIEW':
            deletion.append(dict(row))
        elif row['disposition'] == 'QUEUE_REVIEW':
            entry = dict(row, status='HELD', legacy_status=row['status'], holds=[])
            fixed = resolutions.get(row['reference'])
            if fixed is None:
                entry['holds'].append('MISSING_INPUT_AND_STAGE_RESOLUTION')
            else:
                try:
                    entry['prepared_request'] = _prepare(fixed)
                except (TypeError, ValueError, KeyError) as error:
                    reason = str(error)
                    entry['holds'].append(reason if re.fullmatch('[A-Z_]+', reason) else 'INVALID_RESOLUTION')
            if row['category'] in {'generate_r_exams', 'chem311_testbank'}:
                entry['holds'].append('SPECIALIST_OWNERSHIP_AND_PILOT_HANDOFF_REQUIRED')
            if row['category'] == 'consensus_extract' and fixed is None:
                entry['holds'].append('REGENERATE_MISSING_INPUTS_FROM_VERIFIED_SOURCES')
            if row['category'] in {'improvement', 'research_target'} and fixed is None:
                entry['holds'].append('RECONCILE_TARGET_PATH_AND_COMPLETED_STAGES')
            if not entry['holds']:
                entry['status'] = 'READY_FOR_REVIEWED_INTAKE'
            queue.append(entry)
    groups = defaultdict(list)
    for entry in queue:
        if entry['status'] == 'READY_FOR_REVIEWED_INTAKE':
            groups[entry['prepared_request']['body']['task_id']].append(entry)
    for group in groups.values():
        aliases = [{'reference': row['reference'], 'row_sha256': row['row_sha256'],
                    'attempts': row['attempts'], 'max_attempts': row['max_attempts']} for row in group]
        if len({digest(row['prepared_request']) for row in group}) != 1:
            for row in group:
                row['status'] = 'HELD'
                row['holds'].append('CONFLICTING_DUPLICATE_REQUEST')
            continue
        group[0]['aliases'] = aliases
        for row in group[1:]:
            row['status'] = 'DUPLICATE_OF_PREPARED_REQUEST'
            row['canonical_reference'] = group[0]['reference']
    deletion_counts = Counter((row['source_id'], row['table']) for row in deletion)
    projected_counts = [
        {'source_id': source['source_id'], 'table': table, 'before': before,
         'selected': deletion_counts[(source['source_id'], table)],
         'expected_after_if_applied': before - deletion_counts[(source['source_id'], table)]}
        for source in inventory['sources'] for table, before in source['tables'].items()
        if deletion_counts[(source['source_id'], table)]
    ]
    deletion_manifest = {'schema': 'cochem-legacy-deletion-review/1', 'operation': 'ARCHIVE_AND_REVIEW_ONLY',
                         'snapshot_manifest_sha256': inventory['snapshot_manifest_sha256'], 'rows': deletion,
                         'library_research_ids': [row['primary_key'] for row in deletion if row['category'] == 'library_research'],
                         'counts': dict(sorted(Counter(row['category'] for row in deletion).items())),
                         'table_count_projections': projected_counts,
                         'source_deletion_executed': False}
    return {'schema': 'cochem-legacy-recovery-plan/1', 'inventory_sha256': digest(inventory),
            'snapshot_manifest_sha256': inventory['snapshot_manifest_sha256'],
            'deletion_manifest': deletion_manifest, 'queue_candidates': queue,
            'preserved_counts': dict(sorted(Counter(row['category'] for row in inventory['rows'] if
                row['disposition'] == 'PRESERVE_UNDECIDED').items())),
            'source_writes': 0, 'controller_writes': 0, 'automatic_submission': False}


def select_acceptance_work(plan, *, limit=3):
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Acceptance selection limit must be 1..10')
    ready = sorted((row for row in plan['queue_candidates'] if row['status'] == 'READY_FOR_REVIEWED_INTAKE'),
                   key=lambda row: (row['category'], row['reference']))
    # First represent each category; then fill remaining capacity deterministically.
    selected, categories = [], set()
    for row in ready:
        if row['category'] not in categories and len(selected) < limit:
            selected.append(row); categories.add(row['category'])
    for row in ready:
        if row not in selected and len(selected) < limit:
            selected.append(row)
    return {'schema': 'cochem-useful-work-acceptance-selection/1', 'plan_sha256': digest(plan),
            'work': selected, 'submitted': False, 'completion_requires':
            ['terminal_receipt', 'actual_deliverables', 'independent_checks']}


class SubmissionLedger:
    """Local durable intent ledger; transport is deliberately outside this module.

    A RESERVED entry may represent a POST that succeeded before its receipt was
    saved. It is never offered for dispatch again. Reconcile the exact task ID
    and request with the controller, then call mark_submitted with receipt hash.
    Absence/uncertainty is a hold, not proof that another POST is safe.
    """
    def __init__(self, path):
        self.path = Path(path).absolute()
        ordinary_tree(self.path.parent)
        if self.path.exists():
            ordinary_tree(self.path)
            if self.path.stat().st_nlink != 1:
                raise ValueError('Ledger must be an ordinary single-link file')
        with closing(self._connect()) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS legacy428_submissions (
                task_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL, references_json TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('RESERVED','SUBMITTED')),
                controller_id TEXT, receipt_sha256 TEXT, reserved_at REAL NOT NULL)''')
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def reserve(self, request, *, plan_sha256, references):
        validate_prepared_request(request)
        _sha(plan_sha256)
        if (not isinstance(references, list) or not references or len(references) != len(set(references)) or
                any(not isinstance(ref, str) or not re.fullmatch(r'legacy:[a-f0-9]{64}', ref) for ref in references)):
            raise ValueError('Exact distinct legacy references are required')
        task_id, request_sha256 = request['body']['task_id'], digest(request)
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT request_sha256,state,controller_id,plan_sha256,references_json '
                                  'FROM legacy428_submissions WHERE task_id=?',
                                  (task_id,)).fetchone()
            if existing is not None:
                if existing[0] != request_sha256:
                    raise ValueError('A previously reserved semantic request changed')
                if existing[3] != plan_sha256 or existing[4] != _canonical(sorted(references)):
                    raise ValueError('A previously reserved recovery plan or legacy references changed')
                return {'task_id': task_id, 'may_submit': False,
                        'state': 'RECONCILIATION_REQUIRED' if existing[1] == 'RESERVED' else existing[1],
                        'controller_id': existing[2]}
            db.execute('INSERT INTO legacy428_submissions VALUES(?,?,?,?,?,?,?,?)',
                       (task_id, request_sha256, plan_sha256, _canonical(sorted(references)), 'RESERVED', None, None, time.time()))
            db.commit()
        return {'task_id': task_id, 'may_submit': True, 'state': 'RESERVED', 'controller_id': None}

    def mark_submitted(self, task_id, controller_id, *, receipt_sha256):
        _sha(receipt_sha256)
        if task_id != controller_id:
            raise ValueError('Controller receipt identity must match the deterministic task identity')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,receipt_sha256 FROM legacy428_submissions WHERE task_id=?', (task_id,)).fetchone()
            if row is None:
                raise ValueError('Submission must have a durable reservation first')
            if row[0] == 'SUBMITTED' and row[1] != receipt_sha256:
                raise ValueError('Existing controller receipt changed')
            db.execute("UPDATE legacy428_submissions SET state='SUBMITTED',controller_id=?,receipt_sha256=? WHERE task_id=?",
                       (controller_id, receipt_sha256, task_id))
            db.commit()
        return {'task_id': task_id, 'state': 'SUBMITTED', 'receipt_sha256': receipt_sha256}
