"""In-process legacy snapshot, selection and crash-safe reservation checks."""
from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from scripts.backup_legacy_windows_state import snapshot_databases
from cochem_pipeline.backlog_recovery_428 import (
    SubmissionLedger, build_recovery_plan, digest, inventory_snapshots,
    select_acceptance_work, validate_prepared_request,
)


def archive(tmp_path, rows=None, *, filename='legacy.db', role='kanban'):
    source = tmp_path / filename
    with closing(sqlite3.connect(source)) as db:
        db.execute('CREATE TABLE kanban_tasks(task_id TEXT PRIMARY KEY, workflow_type TEXT, '
                   'status TEXT, file_path TEXT, payload_uri TEXT, payload TEXT, retry_count INTEGER)')
        supplied = rows or [
            ('audit1', 'scout_audit', 'todo', '', '', '{}', 2),
            ('manual1', 'library_research', 'quarantine', '', '', '{}', 3),
            ('quick1', 'quick_reference', 'todo', '', '', '{}', 1),
            ('exam1', 'generate_r_exams', 'blocked_pending_map', '', '', '{}', 4),
            ('yt1', 'youtube_pipeline', 'todo', '', '', '{}', 0),
            ('done1', 'scout_audit', 'done', '', '', '{}', 0),
            ('fixture1', 'scout_audit', 'todo', r'C:\Users\u\AppData\Local\Temp\cochem_test_target_7', '', '{}', 0),
        ]
        db.executemany('INSERT INTO kanban_tasks VALUES(?,?,?,?,?,?,?)',
                       [row for row in supplied if row[1] != 'generate_r_exams'])
        db.execute('CREATE TABLE kanban_tasks_v3(task_id TEXT PRIMARY KEY, workflow_type TEXT, '
                   'status TEXT, file_path TEXT, payload_uri TEXT, payload TEXT, retry_count INTEGER)')
        db.executemany('INSERT INTO kanban_tasks_v3 VALUES(?,?,?,?,?,?,?)',
                       [row for row in supplied if row[1] == 'generate_r_exams'])
        db.commit()
    destination = tmp_path / (filename + '-snapshots')
    snapshot_databases([source], destination)
    manifest = destination / 'snapshot-manifest.json'
    return inventory_snapshots(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(), {str(source): role})


def resolution(tmp_path, *, key='quickref:paper1', stage='quick_reference'):
    source = tmp_path / 'paper.txt'
    source.write_text('Actual captured source text', encoding='utf-8')
    return {'target_key': key, 'stage': stage, 'objective': 'Extract this paper into a useful quick reference.',
            'inputs': [{'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
            'deliverables': [{'path': 'quickref.md', 'checks': ['Title, citation and evidence-linked findings']}],
            'history_disposition': 'Preserve recorded attempts; new workflow requires current budget authority.'}


def test_exact_owner_selections_preserve_sources_and_fixture_rows(tmp_path):
    inv = archive(tmp_path)
    plan = build_recovery_plan(inv)
    assert {r['primary_key'] for r in plan['deletion_manifest']['rows']} == {'audit1', 'manual1'}
    assert plan['deletion_manifest']['operation'] == 'ARCHIVE_AND_REVIEW_ONLY'
    assert plan['deletion_manifest']['library_research_ids'] == ['manual1']
    assert {r['primary_key'] for r in plan['queue_candidates']} == {'quick1', 'exam1'}
    assert all(r['status'] == 'HELD' for r in plan['queue_candidates'])
    assert {r['primary_key']: r['disposition'] for r in inv['rows']}['fixture1'] == 'EXCLUDE_FIXTURE'
    with closing(sqlite3.connect(tmp_path / 'legacy.db')) as db:
        assert db.execute('SELECT COUNT(*) FROM kanban_tasks').fetchone()[0] == 6
        assert db.execute('SELECT COUNT(*) FROM kanban_tasks_v3').fetchone()[0] == 1
    assert plan['controller_writes'] == plan['source_writes'] == 0
    assert plan['deletion_manifest']['table_count_projections'][0]['expected_after_if_applied'] == 4


def test_unknown_category_and_youtube_are_preserved(tmp_path):
    inv = archive(tmp_path, [('x', 'coding', 'blocked', '', '', '{}', 8),
                             ('y', 'youtube_pipeline', 'todo', '', '', '{}', 0)])
    assert all(r['disposition'] == 'PRESERVE_UNDECIDED' for r in inv['rows'])
    assert not build_recovery_plan(inv)['queue_candidates']


def test_resolved_useful_work_has_hash_bound_initial_deliverable_contract(tmp_path):
    inv = archive(tmp_path)
    row = next(r for r in inv['rows'] if r['primary_key'] == 'quick1')
    plan = build_recovery_plan(inv, {row['reference']: resolution(tmp_path)})
    ready = next(r for r in plan['queue_candidates'] if r['primary_key'] == 'quick1')
    assert ready['status'] == 'READY_FOR_REVIEWED_INTAKE'
    request = ready['prepared_request']
    assert 'quickref.md' in request['body']['objective']
    assert 'Title, citation and evidence-linked findings' in request['body']['objective']
    assert request['body']['task_id'].startswith('legacy428-')
    assert request['endpoint'] == '/tasks/submit'
    validate_prepared_request(request)
    accepted = select_acceptance_work(plan, limit=2)
    assert len(accepted['work']) == 1
    assert accepted['work'][0]['reference'] == row['reference']
    assert accepted['completion_requires'] == ['terminal_receipt', 'actual_deliverables', 'independent_checks']


def test_changed_or_missing_inputs_hold_instead_of_inventing_payloads(tmp_path):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'quick1')
    fixed = resolution(tmp_path)
    (tmp_path / 'paper.txt').write_text('changed')
    plan = build_recovery_plan(inv, {ref: fixed})
    candidate = next(r for r in plan['queue_candidates'] if r['reference'] == ref)
    assert candidate['status'] == 'HELD'
    assert candidate['holds'] == ['INPUT_DIGEST_MISMATCH']


def test_exam_owned_work_cannot_be_released_by_resolution_alone(tmp_path):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'exam1')
    plan = build_recovery_plan(inv, {ref: resolution(tmp_path, key='CHEM103:1:1', stage='generate_r_exams')})
    row = next(r for r in plan['queue_candidates'] if r['reference'] == ref)
    assert row['status'] == 'HELD'
    assert 'SPECIALIST_OWNERSHIP_AND_PILOT_HANDOFF_REQUIRED' in row['holds']


def test_semantic_duplicates_share_one_workflow_and_aliases(tmp_path):
    inv = archive(tmp_path, [('a', 'quick_reference', 'todo', '', '', '{}', 2),
                            ('b', 'quick_reference', 'todo', '', '', '{}', 7)])
    fixed = resolution(tmp_path)
    plan = build_recovery_plan(inv, {r['reference']: fixed for r in inv['rows']})
    ready = [r for r in plan['queue_candidates'] if r['status'] == 'READY_FOR_REVIEWED_INTAKE']
    assert len(ready) == 1
    assert len(ready[0]['aliases']) == 2
    assert sorted(a['attempts'] for a in ready[0]['aliases']) == [2, 7]


def test_conflicting_duplicate_requests_are_held(tmp_path):
    inv = archive(tmp_path, [('a', 'quick_reference', 'todo', '', '', '{}', 0),
                            ('b', 'quick_reference', 'todo', '', '', '{}', 0)])
    resolved = {r['reference']: resolution(tmp_path) for r in inv['rows']}
    resolved[inv['rows'][1]['reference']]['objective'] = 'A materially different request'
    plan = build_recovery_plan(inv, resolved)
    assert all(r['status'] == 'HELD' for r in plan['queue_candidates'])
    assert all('CONFLICTING_DUPLICATE_REQUEST' in r['holds'] for r in plan['queue_candidates'])


def test_inventory_requires_exact_hash_and_explicit_roles(tmp_path):
    archive(tmp_path)
    manifest = tmp_path / 'legacy.db-snapshots/snapshot-manifest.json'
    with pytest.raises(ValueError, match='digest'):
        inventory_snapshots(manifest, '0' * 64, {})
    with pytest.raises(ValueError, match='role'):
        inventory_snapshots(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(), {})


def test_stable_source_reference_survives_new_snapshot(tmp_path):
    first = archive(tmp_path)
    source = tmp_path / 'legacy.db'
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE kanban_tasks SET retry_count=99 WHERE task_id='quick1'")
        db.commit()
    dest = tmp_path / 'new-snapshot'
    snapshot_databases([source], dest)
    manifest = dest / 'snapshot-manifest.json'
    second = inventory_snapshots(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(), {str(source): 'kanban'})
    old = next(r for r in first['rows'] if r['primary_key'] == 'quick1')
    new = next(r for r in second['rows'] if r['primary_key'] == 'quick1')
    assert old['reference'] == new['reference']
    assert old['row_sha256'] != new['row_sha256']
    assert new['attempts'] == 99


def test_ledger_crash_window_never_automatically_resubmits(tmp_path):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'quick1')
    plan = build_recovery_plan(inv, {ref: resolution(tmp_path)})
    request = next(r['prepared_request'] for r in plan['queue_candidates'] if r['reference'] == ref)
    ledger = SubmissionLedger(tmp_path / 'ledger.db')
    first = ledger.reserve(request, plan_sha256=digest(plan), references=[ref])
    assert first['may_submit'] is True
    again = SubmissionLedger(tmp_path / 'ledger.db').reserve(request, plan_sha256=digest(plan), references=[ref])
    assert again['may_submit'] is False
    assert again['state'] == 'RECONCILIATION_REQUIRED'
    ledger.mark_submitted(request['body']['task_id'], request['body']['task_id'], receipt_sha256='a' * 64)
    final = ledger.reserve(request, plan_sha256=digest(plan), references=[ref])
    assert final['state'] == 'SUBMITTED'
    assert final['may_submit'] is False


def test_ledger_conflicting_semantic_request_rejected_and_identity_must_match(tmp_path):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'quick1')
    plan = build_recovery_plan(inv, {ref: resolution(tmp_path)})
    request = next(r['prepared_request'] for r in plan['queue_candidates'] if r['reference'] == ref)
    ledger = SubmissionLedger(tmp_path / 'ledger.db')
    ledger.reserve(request, plan_sha256=digest(plan), references=[ref])
    with pytest.raises(ValueError, match='identity'):
        ledger.mark_submitted(request['body']['task_id'], 'another-id', receipt_sha256='a' * 64)
    changed = json.loads(json.dumps(request))
    changed['body']['objective'] += ' Extra requirement.'
    with pytest.raises(ValueError, match='changed'):
        ledger.reserve(changed, plan_sha256=digest(plan), references=[ref])


def test_closed_snapshot_bytes_cannot_be_swapped_under_manifest_pin(tmp_path):
    archive(tmp_path)
    manifest = tmp_path / 'legacy.db-snapshots/snapshot-manifest.json'
    content = json.loads(manifest.read_text())
    snapshot = manifest.parent / content['snapshots'][0]['snapshot']
    with closing(sqlite3.connect(snapshot)) as db:
        db.execute("DELETE FROM kanban_tasks WHERE task_id='quick1'")
        db.commit()
    with pytest.raises(ValueError, match='digest'):
        inventory_snapshots(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(),
                            {str(tmp_path / 'legacy.db'): 'kanban'})


def test_row_bound_holds_whole_inventory_without_partial_release(tmp_path):
    archive(tmp_path)
    manifest = tmp_path / 'legacy.db-snapshots/snapshot-manifest.json'
    with pytest.raises(ValueError, match='bound'):
        inventory_snapshots(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(),
                            {str(tmp_path / 'legacy.db'): 'kanban'}, maximum_rows=2)


def test_exam_evidence_selector_is_exact_and_preserves_other_microcode(tmp_path):
    source = tmp_path / 'frozen.db'
    with closing(sqlite3.connect(source)) as db:
        db.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY, task_id TEXT, job_type TEXT, status TEXT, payload_json TEXT)')
        db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)', [
            (1, 'x', 'micro_code', 'PENDING', '{"course_id":"CHEM311"}'),
            (2, 'CHEM311_ch1', 'micro_code', 'PENDING', '{}'),
            (3, 'x3', 'micro_code', 'PENDING', '{"course_id":"CHEM312"}'),
            (4, 'CHEM311_ch2', 'micro_code', 'COMPLETED', '{}')])
        db.commit()
    snapshot_databases([source], tmp_path / 'snapshot')
    manifest = tmp_path / 'snapshot/snapshot-manifest.json'
    inv = inventory_snapshots(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(), {str(source): 'exam_evidence'})
    plan = build_recovery_plan(inv)
    assert {r['primary_key'] for r in plan['queue_candidates']} == {1, 2}
    assert not plan['deletion_manifest']['rows']
    assert plan['preserved_counts'] == {'micro_code': 1}


@pytest.mark.parametrize('bad_path', ['../escape.txt', 'C:/other/file', '/absolute', 'a\\b', 'a/./b'])
def test_prepared_deliverables_cannot_escape_reviewed_output_root(tmp_path, bad_path):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'quick1')
    fixed = resolution(tmp_path)
    fixed['deliverables'][0]['path'] = bad_path
    row = next(r for r in build_recovery_plan(inv, {ref: fixed})['queue_candidates'] if r['reference'] == ref)
    assert row['holds'] == ['INVALID_DELIVERABLE_PATH']


def test_cli_preparation_is_dry_run_and_preserves_existing_outputs(tmp_path):
    from scripts.prepare_428_backlog import prepare
    archive(tmp_path)
    source = tmp_path / 'legacy.db'
    before = source.read_bytes()
    spec = {'schema': 'cochem-legacy-source-spec/1', 'sources': [{'path': str(source), 'role': 'kanban'}]}
    destination = tmp_path / 'review'
    result = prepare(spec, destination)
    assert result['status'] == 'PREPARED_NO_SUBMISSION_OR_DELETION'
    assert result['submissions'] == result['deletions'] == 0
    assert source.read_bytes() == before
    assert result['ready_acceptance_count'] == 0
    for name, sha in result['pins'].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == sha
    with pytest.raises(ValueError, match='new absolute'):
        prepare(spec, destination)


def test_ledger_receipt_replay_is_idempotent_but_cannot_rebind(tmp_path):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'quick1')
    plan = build_recovery_plan(inv, {ref: resolution(tmp_path)})
    request = next(r['prepared_request'] for r in plan['queue_candidates'] if r['reference'] == ref)
    ledger = SubmissionLedger(tmp_path / 'ledger.db')
    ledger.reserve(request, plan_sha256=digest(plan), references=[ref])
    task_id = request['body']['task_id']
    expected = ledger.mark_submitted(task_id, task_id, receipt_sha256='b' * 64)
    assert ledger.mark_submitted(task_id, task_id, receipt_sha256='b' * 64) == expected
    with pytest.raises(ValueError, match='changed'):
        ledger.mark_submitted(task_id, task_id, receipt_sha256='c' * 64)


def test_full_injected_contract_obeys_actual_planning_intake_bound(tmp_path):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'quick1')
    fixed = resolution(tmp_path)
    fixed['objective'] = 'A' * 15999
    row = next(r for r in build_recovery_plan(inv, {ref: fixed})['queue_candidates'] if r['reference'] == ref)
    assert row['holds'] == ['INTAKE_OBJECTIVE_BOUND_EXCEEDED']
