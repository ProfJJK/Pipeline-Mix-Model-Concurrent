"""Real controller/SQLite projections and physical acceptance artifact checks.

No test here claims Windows identity or subscription execution evidence.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os

import pytest

from cochem_pipeline.operator_views import OperatorViewHistory, acceptance_dashboard, operator_snapshot, resource_plot
from pipeline_tests.test_service import endpoint, request, submitted


def test_document_and_preflight_views_report_their_actual_captured_contracts(endpoint):
    from cochem_pipeline.document_governance import execution_contract
    from cochem_pipeline.planning_governance import digest
    submitted(endpoint)
    endpoint.client.call('/preflight', {'workflow_id': 'captured-preflight'})
    for workflow_id, kind in (('service-workflow', 'document_plan'), ('captured-preflight', 'provider_preflight')):
        result = endpoint.client.call('/operator/workflow/' + workflow_id)
        expected = digest(execution_contract(kind))
        assert result['current_specification']['execution_contract_hashes'][kind] == expected
        for capture in result['governing_requirements']:
            assert capture['captured_contract_type'] == kind
            assert capture['captured_contract_sha256'] == expected
            assert capture['captured_contract_schema'] == execution_contract(kind)['schema']
            assert capture['matches_current_contract'] is True
            assert capture['captured_specification_sha256'] is None  # Test controller has no installed authority capture.


def test_operator_routes_require_authentication_and_preserve_database_authority(endpoint):
    submitted(endpoint)
    for path in ('/operator', '/operator/workflow/service-workflow'):
        assert request(endpoint, 'GET', path)[0] == 401
    claim = endpoint.controller.store.claim('private-controller')
    before = endpoint.controller.store.workflow('service-workflow')
    result = endpoint.client.call('/operator/workflow/service-workflow')
    assert result['read_only'] is True
    assert result['window']['jobs_total'] == 3
    executing = next(row for row in result['prerequisites'] if row['job_id'] == claim['job_id'])
    assert executing['state'] == 'executing'
    synthesis = next(row for row in result['prerequisites'] if row['state'] == 'blocked')
    assert synthesis['reason'] == 'An accepted manifest must create the chapter jobs'
    serialized = json.dumps(result)
    assert claim['attempt_id'] not in serialized
    assert 'private-controller' not in serialized
    assert 'fencing_token' not in serialized
    assert endpoint.controller.store.workflow('service-workflow') == before


def test_routing_panel_reports_real_hold_without_guessing_subscription_balance(endpoint):
    endpoint.client.call('/submit', {'objective': 'Design a short checklist', 'chapter_count': 2,
        'workflow_id': 'routing-view', 'max_dispatches': 4})
    claim = endpoint.controller.store.claim('actual-database-claim')
    endpoint.controller.store.fail(claim['job_id'], claim['attempt_id'], claim['fencing_token'],
        'Captured CLI quota exhaustion', retry=True, category='quota', retry_after_seconds=60)
    result = endpoint.client.call('/operator/workflow/routing-view')
    row = next(item for item in result['queue'] if item['job_id'] == claim['job_id'])
    assert row['score']['score'] == claim['routing']['score_details']['score']
    assert row['captured_candidates'] == claim['routing']['candidates']
    assert row['observed_holds'][0]['reason'] == 'quota'
    assert row['quota']['remaining'] is None
    assert row['quota']['knowledge'] == 'unknown'
    assert row['candidate_is_reserved'] is False
    assert row['dispatches'] == 1


def test_operator_mcp_is_read_only_and_returns_same_controller_projection(endpoint):
    from mcp.shared.memory import create_connected_server_and_client_session
    from cochem_pipeline.server import create_server
    submitted(endpoint)

    async def scenario():
        async with create_connected_server_and_client_session(create_server(endpoint.client)) as client:
            catalog = await client.list_tools()
            tool = next(tool for tool in catalog.tools if tool.name == 'pipeline_operator_view')
            assert tool.annotations.readOnlyHint
            result = await client.call_tool('pipeline_operator_view', {'workflow_id': 'service-workflow'})
            assert not result.isError
            assert result.structuredContent['schema'] == 'cochem-operator/4.2.7'
            assert result.structuredContent['acceptance']['all_verified'] is False
            rejected = await client.call_tool('pipeline_operator_view', {'workflow_id': '../../health'})
            assert rejected.isError
    asyncio.run(scenario())


def _catalog(tmp_path, *, platforms=('Windows',)):
    (tmp_path / 'docs').mkdir()
    (tmp_path / '4.2.7_SRS.md').write_text('S427-TEST-001 requires physical evidence.\nS427-TEST-002 requires native evidence.\n')
    specification_sha256 = hashlib.sha256((tmp_path / '4.2.7_SRS.md').read_bytes()).hexdigest()
    definitions = {'revision': 'owner-amendment-test', 'specification_sha256': specification_sha256, 'requirements': [
        {'id': identifier, 'chapter': 15, 'requirement': 'Physical acceptance',
         'required_platforms': list(platforms), 'owner_decisions': ['Accepted suggestion I-15'],
         'remediation': 'Run the required platform acceptance harness'}
        for identifier in ('S427-TEST-001', 'S427-TEST-002')]}
    (tmp_path / 'docs/requirements_4.2.7.json').write_text(json.dumps(definitions))
    artifact = b'Physical test artifact bytes, explicitly a test fixture.\n'
    (tmp_path / 'docs/physical-result.txt').write_bytes(artifact)
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/controller.py').write_text('assert True\n')
    (tmp_path / 'uv.lock').write_text('version = 1\n')
    manifest = {'files': {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
                         for name in ('src/controller.py', 'uv.lock')}}
    (tmp_path / 'docs/source.json').write_text(json.dumps(manifest))
    manifest_hash = hashlib.sha256((tmp_path / 'docs/source.json').read_bytes()).hexdigest()
    evidence = {'specification_sha256': specification_sha256, 'evidence': [{'id': row['id'], 'artifact': 'docs/physical-result.txt',
        'sha256': hashlib.sha256(artifact).hexdigest(), 'platform': 'POSIX',
        'tested_source_manifest': 'docs/source.json', 'tested_source_manifest_sha256': manifest_hash,
        'revision': 'owner-amendment-test', 'status': 'passed'} for row in definitions['requirements']]}
    (tmp_path / 'docs/acceptance_4.2.7.json').write_text(json.dumps(evidence))
    return definitions, evidence


def test_acceptance_requires_target_platform_and_preserves_release_remediation(tmp_path):
    _catalog(tmp_path)
    result = acceptance_dashboard(tmp_path)
    assert result['catalog_complete']
    assert not result['all_verified']
    assert result['counts'] == {'mandatory': 2, 'verified': 0, 'unverified': 2}
    assert all(row['evidence'][0]['verified'] for row in result['requirements'])
    assert all(row['remaining_action'] for row in result['release_checklist'])


def test_acceptance_never_ignores_missing_rows_changed_bytes_or_later_failure(tmp_path):
    _, evidence = _catalog(tmp_path, platforms=('POSIX',))
    assert acceptance_dashboard(tmp_path)['all_verified']
    evidence['evidence'].append({**evidence['evidence'][0], 'status': 'failed'})
    (tmp_path / 'docs/acceptance_4.2.7.json').write_text(json.dumps(evidence))
    result = acceptance_dashboard(tmp_path)
    assert not result['all_verified']
    assert result['counts']['verified'] == 1
    (tmp_path / 'docs/physical-result.txt').write_text('Changed artifact bytes')
    assert acceptance_dashboard(tmp_path)['counts']['verified'] == 0
    with (tmp_path / '4.2.7_SRS.md').open('a') as stream:
        stream.write('S427-TEST-003 is mandatory too.\n')
    result = acceptance_dashboard(tmp_path)
    assert result['counts']['mandatory'] == 3
    assert result['catalog_complete'] is False
    assert result['requirements'][2]['catalog_present'] is False


def test_external_or_stale_revision_artifacts_cannot_turn_dashboard_green(tmp_path):
    _, evidence = _catalog(tmp_path, platforms=('POSIX',))
    evidence['evidence'][0]['artifact'] = '../outside.txt'
    evidence['evidence'][1]['revision'] = 'old-release'
    (tmp_path / 'docs/acceptance_4.2.7.json').write_text(json.dumps(evidence))
    result = acceptance_dashboard(tmp_path)
    assert result['counts']['verified'] == 0
    assert 'outside' in result['requirements'][0]['evidence'][0]['verification']
    assert 'revision mismatch' in result['requirements'][1]['evidence'][0]['verification']


def test_same_requirement_ids_and_revision_cannot_hide_changed_normative_words(tmp_path):
    definitions, _ = _catalog(tmp_path, platforms=('POSIX',))
    assert acceptance_dashboard(tmp_path)['all_verified']
    specification = tmp_path / '4.2.7_SRS.md'
    specification.write_text(specification.read_text().replace('physical evidence', 'stronger new physical evidence'))
    result = acceptance_dashboard(tmp_path)
    assert result['catalog_source_verified'] is False
    assert not result['catalog_complete'] and not result['all_verified']
    definitions['specification_sha256'] = hashlib.sha256(specification.read_bytes()).hexdigest()
    (tmp_path / 'docs/requirements_4.2.7.json').write_text(json.dumps(definitions))
    result = acceptance_dashboard(tmp_path)
    assert result['catalog_source_verified'] is True
    assert result['counts']['verified'] == 0  # Older evidence is bound to the older source bytes.


def test_resource_plot_separates_measured_units_and_missing_samples():
    empty = resource_plot([None, {'measured_at': None}])
    assert empty['samples'] == []
    assert 'No physical samples available' in empty['svg']
    measured = {'measured_at': 100., 'capacity': 2, 'state': 'throttled',
        'measurements': {'cpu': {'percent': 84.5}, 'memory': {'available_mb': 4096}},
        'reasons': ['Available memory constrains admission']}
    result = resource_plot([measured, measured])
    assert len(result['samples']) == 1
    assert result['samples'][0]['limiting_reasons'] == measured['reasons']
    assert result['continuous_monitoring_claimed'] is False
    assert 'Admitted capacity (agents)' in result['svg']
    assert 'Measured CPU (%)' in result['svg']
    assert 'Available RAM (MB)' in result['svg']


def test_unobserved_deployment_identities_are_not_attested(endpoint):
    endpoint.controller.config.workers = {'slot-1': {'name': 'DedicatedAccount', 'credential_target': 'private-secret-target'}}
    result = operator_snapshot(endpoint.controller)
    worker = next(row for row in result['deployment']['nodes'] if row['kind'] == 'worker')
    assert worker['attestation'] == 'not_observed'
    assert worker['observed_accounts'] == []
    assert result['deployment']['unobserved_is_healthy'] is False
    assert 'private-secret-target' not in json.dumps(result)
    assert 'DedicatedAccount' in result['deployment']['mermaid'] or worker['configured_identity'] == 'DedicatedAccount'


def test_real_http_latency_observation_is_bounded_metadata_not_request_content(endpoint, tmp_path):
    import sqlite3
    from cochem_pipeline.operations_policy import WorkloadObjectives
    if os.name == 'nt':
        from cochem_pipeline import windows
        try:
            windows.require_system()
        except windows.WindowsIsolationError:
            pytest.skip('Native protected metrics require the staged Windows SYSTEM acceptance session')
    root = tmp_path / 'protected-observations'
    root.mkdir(mode=0o700)
    objectives = WorkloadObjectives(root)
    endpoint.controller.objectives = objectives
    try:
        response = endpoint.client.call('/submit', {'objective': 'private objective must stay out of metrics',
            'chapter_count': 2, 'workflow_id': 'private-workflow-identifier'})
        assert response['status'] == 'IN_PROGRESS'
        endpoint.client.call('/workflow/private-workflow-identifier')
    finally:
        objectives.close()
        del endpoint.controller.objectives
    with sqlite3.connect(objectives.database) as db:
        rows = db.execute('SELECT workload,operation,duration_seconds,success,evidence_id FROM observations').fetchall()
    assert len(rows) == 2
    assert {row[1] for row in rows} == {'/submit', '/workflow'}
    assert all(row[0] == 'interactive' and row[2] > 0 and row[3] == 1 for row in rows)
    assert 'private-workflow-identifier' not in json.dumps(rows)
    assert 'private objective' not in json.dumps(rows)


def test_packaged_catalog_fallback_still_requires_physical_artifacts(tmp_path):
    _catalog(tmp_path, platforms=('POSIX',))
    for name in ('requirements_4.2.7.json', 'acceptance_4.2.7.json'):
        (tmp_path / 'docs' / name).rename(tmp_path / name)
    assert acceptance_dashboard(tmp_path)['all_verified']
    (tmp_path / 'docs/physical-result.txt').unlink()
    assert not acceptance_dashboard(tmp_path)['all_verified']


def test_job_specific_governance_and_event_cursor_read_real_retained_rows(endpoint):
    submitted(endpoint)
    claimed = endpoint.controller.store.claim('private-controller')
    path = '/operator/job/' + claimed['job_id']
    assert request(endpoint, 'GET', path)[0] == 401
    result = endpoint.client.call(path + '?after_event_id=0')
    assert result['job_id'] == claimed['job_id']
    assert result['workflow_id'] == 'service-workflow'
    assert [row['job_id'] for row in result['governing_requirements']] == [claimed['job_id']]
    assert all(row['job_id'] == claimed['job_id'] for row in result['timeline'])
    cursor = result['window']['next_event_cursor']
    assert cursor > 0
    assert endpoint.client.call(path + '?after_event_id=' + str(cursor))['timeline'] == []
    status, _ = request(endpoint, 'GET', path + '?after_event_id=-1', authorization='Bearer ' + endpoint.token)
    assert status == 400
    status, _ = request(endpoint, 'GET', path + '?unknown=true', authorization='Bearer ' + endpoint.token)
    assert status == 400


def test_manual_preflight_authenticates_and_submits_one_bounded_routed_job(endpoint):
    assert request(endpoint, 'POST', '/preflight', {'workflow_id': 'preflight-view'})[0] == 401
    assert endpoint.controller.store.list_workflows() == []
    first = endpoint.client.call('/preflight', {'workflow_id': 'preflight-view'})
    again = endpoint.client.call('/preflight', {'workflow_id': 'preflight-view'})
    assert first == again
    native = [row for row in first['jobs'] if row['kind'] == 'PREFLIGHT_REQUEST']
    assert len(native) == 1
    assert native[0]['receipt'] is None
    assert 1 <= native[0]['routing']['max_dispatches'] <= 3
    assert len(native[0]['routing']['candidates']) >= 2
    denied, _ = request(endpoint, 'POST', '/preflight', {'model': 'forced-model'},
                        authorization='Bearer ' + endpoint.token)
    assert denied == 400
    assert len(endpoint.controller.store.list_workflows()) == 1


def test_queue_preview_skips_observed_hold_matches_atomic_claim_and_does_not_mutate(endpoint):
    workflow = submitted(endpoint)
    pending = next(job for job in workflow['jobs'] if job['kind'] == 'MANIFEST_GENERATOR')
    preferred = pending['routing']['candidates'][0]
    endpoint.controller.store.set_route_hold('model', preferred['key'], 60, 'busy')
    before = endpoint.controller.store.workflow('service-workflow')
    result = endpoint.client.call('/operator/job/' + pending['job_id'])
    preview = result['queue'][0]['eligibility_preview']
    assert preview['candidate_index'] == 1
    assert preview['skipped'][0]['reason'] == 'busy'
    assert preview['prediction_only'] and preview['unknown_until_atomic_claim']
    assert preview['host_admission_available'] is None  # This fixture has no hardware probe.
    assert endpoint.controller.store.workflow('service-workflow') == before
    claimed = endpoint.controller.store.claim('actual-comparison-claim')
    assert claimed['route']['key'] == preview['eligible_candidate']['key']


def _host_sample(index):
    """A host sample shaped like the live Warden transition telemetry (over 7 KB compact JSON)."""
    disks = {f'disk-{number:02d}': {'mount': f'V{number:02d}:\\', 'read_iops': 1.5 + index, 'write_iops': 2.5,
             'busy_percent': 12.5, 'free_mb': 100000 + index, 'total_mb': 500000, 'queue_depth': 0.25,
             'filesystem': 'NTFS', 'serial': f'serial-{number:04d}', 'available': True} for number in range(32)}
    return {'measured_at': 1000.0 + index, 'capacity': index % 4, 'state': ('steady', 'throttled')[index % 2],
            'reasons': [f'Measured pressure {index}'] if index % 2 else [], 'action': 'admit',
            'policy': {f'limit_{number:02d}': {'pause': 85 + number, 'resume': 70 + number} for number in range(24)},
            'measurements': {'cpu': {'percent': float(index % 100), 'count': 16,
                                     'per_core_percent': [float((index + core) % 100) for core in range(16)]},
                             'memory': {'available_mb': 30000 - index, 'total_mb': 65536, 'commit_free_mb': 20000},
                             'disks': disks, 'gpus': {'available': False, 'devices': []}},
            'workspaces': {f'slot-{number}': {'path': f'R:\\slot-{number}\\workspace', 'free_mb': 4096}
                           for number in range(6)}}


def _observed_events(endpoint, count):
    """Append real store events; each transition embeds the then-current full host sample."""
    store = endpoint.controller.store
    workflow = submitted(endpoint)
    job_id = next(job['job_id'] for job in workflow['jobs'] if job['kind'] == 'MANIFEST_GENERATOR')
    with store._write() as conn:
        job = store._get(conn, job_id)
        for index in range(count):
            store.set_transition_telemetry(None if index % 50 == 7 else _host_sample(index))
            details = ({'reason': f'observation {index}'} if index % 3 == 0 else
                       {'error': f'failure {index}'} if index % 3 == 1 else {})
            store._event(conn, job, 'HOST_OBSERVATION', **details)
    return job_id


def _expected_timeline(events):
    return [{'id': event['id'], 'at': event['timestamp'], 'job_id': event['job_id'], 'event': event['event'],
             'reason': event['details'].get('reason', event['details'].get('error'))} for event in events]


def _deployment(tmp_path, name='deployment'):
    root = tmp_path / name
    root.mkdir()
    _catalog(root, platforms=('POSIX',))
    return root


def test_slim_event_keeps_timeline_reason_semantics_and_plotted_scalars_only():
    from cochem_pipeline.operator_views import _slim_event
    sample = {**_host_sample(3), 'cpu_percent': 1.0}
    event = {'id': 9, 'workflow_id': 'w', 'job_id': 'j', 'timestamp': 5.0, 'event': 'CLAIMED',
             'details': {'reason': None, 'error': 'kept', 'attempt_id': 'private',
                         'telemetry': {'host_sample': sample, 'pid': 4}}}
    assert _slim_event(event) == {'id': 9, 'timestamp': 5.0, 'job_id': 'j', 'event': 'CLAIMED', 'details': {
        'reason': None, 'error': 'kept', 'telemetry': {'host_sample': {
            'measured_at': sample['measured_at'], 'capacity': sample['capacity'], 'state': sample['state'],
            'reasons': sample['reasons'], 'cpu_percent': 1.0,
            'measurements': {'cpu': {'percent': sample['measurements']['cpu']['percent']},
                             'memory': {'available_mb': sample['measurements']['memory']['available_mb']}}}}}}
    assert _slim_event({'id': 1, 'details': {}})['details'] == {'telemetry': {'host_sample': None}}
    assert _slim_event({'id': 2, 'details': {'telemetry': {'host_sample': {'measured_at': 3}}}})['details'] == {
        'telemetry': {'host_sample': {'measured_at': 3}}}


def test_resource_plot_keeps_raw_measurements_only_on_the_latest_point():
    older = {'measured_at': 100., 'capacity': 2, 'state': 'steady', 'reasons': [],
             'measurements': {'cpu': {'percent': 10.}, 'memory': {'available_mb': 4096}, 'disks': {'C:': 'older'}}}
    newer = {'measured_at': 200., 'capacity': 1, 'state': 'throttled', 'reasons': ['CPU'],
             'measurements': {'cpu': {'percent': 20.}, 'memory': {'available_mb': 2048}, 'disks': {'C:': 'newer'}}}
    result = resource_plot([newer, older])
    assert [point['at'] for point in result['samples']] == [100., 200.]
    assert 'measurements' not in result['samples'][0]
    assert result['samples'][0]['cpu_percent'] == 10. and result['samples'][0]['available_memory_mb'] == 4096
    assert result['samples'][1]['measurements'] == newer['measurements']
    assert result['measurements_scope'] == 'latest_point_only'
    # A slimmed event copy of the newest measurement is followed by the live snapshot's full block.
    slim = {**newer, 'measurements': {'cpu': {'percent': 20.}, 'memory': {'available_mb': 2048}}}
    combined = resource_plot([older, slim, newer])
    assert combined['samples'][-1]['measurements'] == newer['measurements']
    assert combined['svg'] == result['svg']


def test_two_hundred_full_host_samples_give_a_small_body_with_unchanged_timeline_and_plot(endpoint, tmp_path, monkeypatch):
    from cochem_pipeline.service import redact
    store = endpoint.controller.store
    _observed_events(endpoint, 200)
    status = endpoint.controller.status
    monkeypatch.setattr(endpoint.controller, 'status', lambda: {**status(), 'admission': store.transition_telemetry})
    with store._connection() as conn:
        full = sorted((store._decode_event(row) for row in conn.execute(
            'SELECT * FROM pipeline_events ORDER BY id DESC LIMIT 200')), key=lambda event: event['id'])
    samples = [event['details']['telemetry']['host_sample'] for event in full]
    measured = [sample for sample in samples if sample is not None]
    assert len(full) == 200 and len(measured) == 196
    assert all(len(json.dumps(sample, separators=(',', ':'))) > 7000 for sample in measured)
    # Copying every raw block into the plot, as r4 did, would exceed the bound on its own.
    assert sum(len(json.dumps(sample['measurements'], separators=(',', ':'))) for sample in measured) > 300_000
    result = operator_snapshot(endpoint.controller, source_root=_deployment(tmp_path), history=OperatorViewHistory())
    assert result['timeline'] == _expected_timeline(full)
    assert result['window']['events_truncated'] is True
    plotted = result['resources']['samples']
    expected = resource_plot(samples + [store.transition_telemetry])
    assert plotted == expected['samples']
    assert result['resources']['svg'] == expected['svg']
    assert [point['at'] for point in plotted] == [sample['measured_at'] for sample in measured]
    assert [point['capacity'] for point in plotted] == [sample['capacity'] for sample in measured]
    assert [point['state'] for point in plotted] == [sample['state'] for sample in measured]
    assert [point['cpu_percent'] for point in plotted] == [sample['measurements']['cpu']['percent'] for sample in measured]
    assert [point['available_memory_mb'] for point in plotted] == [
        sample['measurements']['memory']['available_mb'] for sample in measured]
    assert [point['limiting_reasons'] for point in plotted] == [sample['reasons'] for sample in measured]
    assert all('measurements' not in point for point in plotted[:-1])
    assert plotted[-1]['measurements'] == store.transition_telemetry['measurements']
    body = json.dumps(redact(result), ensure_ascii=False).encode('utf-8')
    assert len(body) < 300_000


def test_event_cursor_pages_slimmed_events_in_order_without_gaps(endpoint, tmp_path):
    store = endpoint.controller.store
    job_id = _observed_events(endpoint, 230)
    with store._connection() as conn:
        full = [store._decode_event(row) for row in conn.execute('SELECT * FROM pipeline_events ORDER BY id')]
    root, history = _deployment(tmp_path), OperatorViewHistory()
    cursor, timeline, truncated = 0, [], []
    for _ in range(4):
        page = operator_snapshot(endpoint.controller, after_event_id=cursor, source_root=root, history=history)
        assert page['window']['after_event_id'] == cursor
        if not page['timeline']:
            assert page['window']['next_event_cursor'] == cursor
            break
        assert len(page['timeline']) <= 200
        timeline.extend(page['timeline'])
        truncated.append(page['window']['events_truncated'])
        cursor = page['window']['next_event_cursor']
        assert cursor == page['timeline'][-1]['id']
    else:
        pytest.fail('Event cursor did not reach the end of the retained events')
    assert truncated == [True, False]
    assert timeline == _expected_timeline(full)
    scoped = operator_snapshot(endpoint.controller, job_id=job_id, after_event_id=full[-31]['id'],
                               source_root=root, history=history)
    assert scoped['timeline'] == _expected_timeline(full[-30:])


def test_acceptance_cache_returns_identical_copies_and_rebuilds_on_ledger_bytes_or_mtime(tmp_path, monkeypatch):
    from cochem_pipeline import operator_views
    _, evidence = _catalog(tmp_path, platforms=('POSIX',))
    builds = []
    build = operator_views.acceptance_dashboard
    monkeypatch.setattr(operator_views, 'acceptance_dashboard', lambda root: builds.append(root) or build(root))
    clock = [1000.0]
    history = OperatorViewHistory(clock=lambda: clock[0])
    first = history.acceptance_snapshot(tmp_path)
    assert first == build(tmp_path) and first['all_verified']
    copy = history.acceptance_snapshot(tmp_path)
    assert copy == first and len(builds) == 1
    copy['requirements'].clear()  # Callers get their own copy; the cache is not shared mutable state.
    assert history.acceptance_snapshot(tmp_path) == first and len(builds) == 1
    evidence['evidence'].append({**evidence['evidence'][0], 'status': 'failed'})
    (tmp_path / 'docs/acceptance_4.2.7.json').write_text(json.dumps(evidence))
    changed = history.acceptance_snapshot(tmp_path)
    assert len(builds) == 2 and changed == build(tmp_path)
    assert not changed['all_verified'] and changed['counts']['verified'] == 1
    specification = tmp_path / '4.2.7_SRS.md'
    observed = specification.stat()
    os.utime(specification, ns=(observed.st_atime_ns, observed.st_mtime_ns + 2_000_000_000))
    assert history.acceptance_snapshot(tmp_path) == changed and len(builds) == 3
    # Evidence artifacts are outside the key; they are re-verified once the 60 s TTL expires.
    (tmp_path / 'docs/physical-result.txt').write_text('Changed artifact bytes')
    clock[0] += 59
    assert history.acceptance_snapshot(tmp_path) == changed and len(builds) == 3
    clock[0] += 2
    expired = history.acceptance_snapshot(tmp_path)
    assert len(builds) == 4 and expired == build(tmp_path) and expired['counts']['verified'] == 0


def test_operator_snapshot_reuses_cached_acceptance_per_history_and_source_root(endpoint, tmp_path, monkeypatch):
    from cochem_pipeline import operator_views
    submitted(endpoint)
    first_root, second_root = _deployment(tmp_path, 'first'), _deployment(tmp_path, 'second')
    (second_root / 'docs/physical-result.txt').write_text('Different bytes in another deployment')
    builds = []
    build = operator_views.acceptance_dashboard
    monkeypatch.setattr(operator_views, 'acceptance_dashboard', lambda root: builds.append(root) or build(root))
    history = OperatorViewHistory()
    first = operator_snapshot(endpoint.controller, source_root=first_root, history=history)
    again = operator_snapshot(endpoint.controller, source_root=first_root, history=history)
    assert first['acceptance'] == again['acceptance'] == build(first_root)
    assert first['acceptance']['all_verified'] and len(builds) == 1
    assert first['current_specification']['sha256'] == first['acceptance']['specification_sha256']
    other = operator_snapshot(endpoint.controller, source_root=second_root, history=history)
    assert not other['acceptance']['all_verified'] and len(builds) == 2
    assert operator_snapshot(endpoint.controller, source_root=first_root, history=history)['acceptance'] == first['acceptance']
    assert len(builds) == 2
    operator_snapshot(endpoint.controller, source_root=first_root)  # Without a history every call rebuilds, as before.
    assert len(builds) == 3
