"""Real loopback HTTP/temp SQLite only; no native workers or host lifecycle."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest

from cochem_pipeline.backlog_intake_428 import load_selected_work, run_selected_intake
from cochem_pipeline.backlog_recovery_428 import SubmissionLedger, build_recovery_plan, digest, select_acceptance_work
from cochem_supervisor.probes import ControllerClient, ControllerHttpError
from pipeline_tests.test_backlog_recovery_428 import archive, resolution
from pipeline_tests.test_service import endpoint, request
from pipeline_tests.test_task_interface_428 import task_endpoint


@pytest.fixture
def intake(tmp_path, task_endpoint):
    inv = archive(tmp_path)
    ref = next(r['reference'] for r in inv['rows'] if r['primary_key'] == 'quick1')
    plan = build_recovery_plan(inv, {ref: resolution(tmp_path)})
    selection = select_acceptance_work(plan)
    binding = dict(schema='cochem-backlog-controller-binding/1', version='4.2.8', instance_id='inert-instance',
                   pid=123, process_started_at=100.0, source_root=str(tmp_path / 'installed' / 'Lib'))
    health = dict(binding, service_identity='SYSTEM', admission_capacity=0, trip_errors={},
                  task_planning={'status': 'ENABLED', 'execution_materialization': 'CONNECTED'})
    task_endpoint.controller.status = lambda: deepcopy(health)
    client = ControllerClient(task_endpoint.port, task_endpoint.client.token_file)
    ledger = SubmissionLedger(tmp_path / 'submissions.db')
    return client, ledger, selection, plan, binding, health, task_endpoint


def run(intake, **kwargs):
    client, ledger, selection, plan, binding, *_ = intake
    return run_selected_intake(client, ledger, selection, plan, expected_controller=binding, **kwargs)


def test_selected_pins_and_exact_plan_rows_are_required(intake, tmp_path):
    _, _, selection, plan, *_ = intake
    paths = []
    for name, value in [('selection.json', selection), ('plan.json', plan)]:
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding='utf-8')
        paths.append((path, hashlib.sha256(path.read_bytes()).hexdigest()))
    loaded, loaded_plan = load_selected_work(*paths[0], *paths[1])
    assert loaded == selection and loaded_plan == plan
    paths[0][0].write_text('{}')
    with pytest.raises(ValueError, match='digest'):
        load_selected_work(*paths[0], *paths[1])


def test_actual_authenticated_intake_reserves_before_one_post_and_reconciles(intake):
    client, ledger, selection, _, _, _, endpoint = intake
    task_id = selection['work'][0]['prepared_request']['body']['task_id']
    calls = []
    original = client.call

    def observed(operation, data=None):
        calls.append(operation)
        if operation == '/tasks/submit':
            with ledger._connect() as db:
                assert db.execute('SELECT state FROM legacy428_submissions WHERE task_id=?', (task_id,)).fetchone() == ('RESERVED',)
        return original(operation, data)

    client.call = observed
    first = run(intake, submit=True)
    assert first['status'] == 'SUBMITTED_OR_RECONCILED'
    assert first['work'][0]['task_id'] == task_id
    assert first['work'][0]['status'] == 'SUBMITTED'
    assert first['completion_verified'] is False
    second = run(intake, submit=True)
    assert second['work'][0]['status'] == 'RECONCILED'
    assert calls.count('/tasks/submit') == 1
    assert endpoint.controller.task_planning.has_task(task_id)
    assert '/coding/projects' in calls


def test_timeout_after_commit_reconciles_exact_identity_without_another_post(intake):
    client = intake[0]
    original = client.call
    posts = []

    def timeout(operation, data=None):
        response = original(operation, data)
        if operation == '/tasks/submit':
            posts.append(data)
            raise TimeoutError('remote or credential text must not be recorded')
        return response

    client.call = timeout
    result = run(intake, submit=True)
    assert result['work'][0]['status'] == 'RECONCILED_AFTER_UNCERTAIN_POST'
    assert run(intake, submit=True)['work'][0]['status'] == 'RECONCILED'
    assert len(posts) == 1
    assert 'credential text' not in json.dumps(result)


def test_uncertain_absence_never_resubmits_even_after_restart(intake):
    client, ledger, _, _, _, _, _ = intake
    original = client.call
    posts = []

    def no_response(operation, data=None):
        if operation == '/tasks/submit':
            posts.append(data)
            raise TimeoutError('uncertain')
        return original(operation, data)

    client.call = no_response
    assert run(intake, submit=True)['work'][0]['reason'] == 'UNCERTAIN_SUBMISSION'
    intake = (client, SubmissionLedger(ledger.path), *intake[2:])
    assert run(intake, submit=True)['work'][0]['reason'] == 'RESERVED_TASK_NOT_FOUND'
    assert len(posts) == 1


def test_readonly_default_never_reserves_or_submits(intake):
    result = run(intake)
    assert result['status'] == 'READY_NO_SUBMISSION'
    with intake[1]._connect() as db:
        assert db.execute('SELECT count(*) FROM legacy428_submissions').fetchone()[0] == 0


@pytest.mark.parametrize('mutation', ['disabled', 'unconnected', 'identity', 'unregistered', 'fixture', 'modified_input'])
def test_preconditions_hold_before_any_post(intake, mutation):
    client, ledger, selection, plan, _, health, _ = intake
    if mutation == 'disabled':
        health['task_planning']['status'] = 'DISABLED'
    elif mutation == 'unconnected':
        health['task_planning']['execution_materialization'] = 'NOT_CONNECTED'
    elif mutation == 'identity':
        health['instance_id'] = 'replacement'
    elif mutation in ('unregistered', 'fixture'):
        row = selection['work'][0]
        req = row['prepared_request']
        req['body']['project_id'] = 'windows-acceptance' if mutation == 'fixture' else 'absent-project'
        req['identity']['project_id'] = req['body']['project_id']
        req['body']['task_id'] = 'legacy428-' + digest(req['identity'])
        plan['queue_candidates'] = [row]
        selection['plan_sha256'] = digest(plan)
    else:
        Path(selection['work'][0]['prepared_request']['contract']['inputs'][0]['path']).write_text('changed')
    calls = []
    original = client.call
    client.call = lambda operation, data=None: (calls.append(operation), original(operation, data))[1]
    result = run(intake, submit=True)
    assert result['status'] == 'HELD_PRESERVE_EVIDENCE'
    assert '/tasks/submit' not in calls
    with ledger._connect() as db:
        assert db.execute('SELECT count(*) FROM legacy428_submissions').fetchone()[0] == 0


def test_input_change_after_reservation_prevents_post(intake):
    ledger = intake[1]
    original = ledger.reserve

    def change(request, **kwargs):
        result = original(request, **kwargs)
        Path(request['contract']['inputs'][0]['path']).write_text('changed after reservation')
        return result

    ledger.reserve = change
    result = run(intake, submit=True)
    assert result['work'][0]['status'] == 'HELD'
    assert not intake[-1].controller.task_planning.has_task(result['work'][0]['task_id'])


def test_existing_other_objective_is_a_hold_not_a_reused_receipt(intake):
    task_id = intake[2]['work'][0]['prepared_request']['body']['task_id']
    intake[-1].controller.task_planning.submit('Different objective', task_id)
    result = run(intake, submit=True)
    assert result['work'][0]['reason'] == 'TASK_IDENTITY_MISMATCH'
    assert intake[-1].controller.task_planning.task_status(task_id)['task']['objective'] == 'Different objective'


def test_absent_route_is_typed_but_internal_keyerror_is_never_absence(intake):
    client, _, selection, _, _, _, endpoint = intake
    task_id = selection['work'][0]['prepared_request']['body']['task_id']
    with pytest.raises(ControllerHttpError) as missing:
        client.call('/tasks/status/' + task_id)
    assert missing.value.status == 404 and missing.value.error_code == 'TASK_NOT_FOUND'
    endpoint.controller.task_planning.submit('Some task', task_id)
    endpoint.controller.task_status = lambda _: (_ for _ in ()).throw(KeyError('internal-secret'))
    with pytest.raises(ControllerHttpError) as internal:
        client.call('/tasks/status/' + task_id)
    assert internal.value.status == 400 and internal.value.error_code is None
    assert 'internal-secret' not in str(internal.value)


def test_exact_selection_does_not_allow_injected_or_specialist_work(intake):
    selection = intake[2]
    selection['work'][0] = deepcopy(selection['work'][0])
    selection['work'][0]['category'] = 'youtube_pipeline'
    result = run(intake, submit=True)
    assert result['status'] == 'HELD_PRESERVE_EVIDENCE'


def test_two_callers_share_one_durable_reservation_and_only_one_post(intake):
    client = intake[0]
    posts = []
    original = client.call

    def observe(operation, data=None):
        if operation == '/tasks/submit':
            posts.append(data)
        return original(operation, data)

    client.call = observe
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(intake, submit=True), range(2)))
    assert len(posts) == 1
    assert any(result['status'] == 'SUBMITTED_OR_RECONCILED' for result in results)
    assert run(intake, submit=True)['status'] == 'SUBMITTED_OR_RECONCILED'


def test_reserved_plan_and_aliases_cannot_be_rebound(intake):
    ledger, selection, plan = intake[1:4]
    row = selection['work'][0]
    ledger.reserve(row['prepared_request'], plan_sha256=digest(plan), references=[row['reference']])
    with pytest.raises(ValueError, match='changed'):
        ledger.reserve(row['prepared_request'], plan_sha256='a' * 64, references=[row['reference']])
    with pytest.raises(ValueError, match='changed'):
        ledger.reserve(row['prepared_request'], plan_sha256=digest(plan), references=['legacy:' + 'a' * 64])


def test_unknown_404_does_not_prove_task_absent(intake):
    client = intake[0]
    original = client.call

    def unsupported(operation, data=None):
        if operation.startswith('/tasks/status/'):
            raise ControllerHttpError(404)
        return original(operation, data)

    client.call = unsupported
    result = run(intake, submit=True)
    assert result['work'][0]['reason'] == 'CONTROLLER_HTTP_ERROR'
    assert result['post_attempts'] == 0


def test_cli_keeps_fresh_sanitized_evidence_and_defaults_to_no_post(intake, tmp_path, capsys):
    from scripts.submit_428_selected_work import main
    client, ledger, selection, plan, binding, *_ = intake
    argv = []
    for name, value in [('selection', selection), ('plan', plan), ('controller-binding', binding),
                        ('client-config', {'port': client.port, 'token_file': str(client.token_file)})]:
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        argv += ['--' + name, str(path), '--' + name + '-sha256', hashlib.sha256(path.read_bytes()).hexdigest()]
    target = tmp_path / 'inspection'
    argv += ['--ledger', str(ledger.path), '--destination', str(target)]
    assert main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['post_attempts'] == 0
    assert json.loads((target / 'result.json').read_text())['status'] == 'READY_NO_SUBMISSION'
    assert client.token_file.read_text() not in json.dumps(printed)
    assert selection['work'][0]['prepared_request']['body']['objective'] not in json.dumps(printed)
    with pytest.raises(SystemExit):
        main(argv)


def test_later_selected_work_stays_untouched_after_uncertain_post(intake):
    client, _, selection, plan, *_ = intake
    row = deepcopy(selection['work'][0])
    row['reference'] = 'legacy:' + 'b' * 64
    row['aliases'] = [dict(row['aliases'][0], reference=row['reference'])]
    req = row['prepared_request']
    req['identity']['target_key'] = 'quickref:paper2'
    req['body']['task_id'] = 'legacy428-' + digest(req['identity'])
    selection['work'].append(row)
    plan['queue_candidates'].append(row)
    selection['plan_sha256'] = digest(plan)
    original = client.call
    posts = []

    def uncertain(operation, data=None):
        if operation == '/tasks/submit':
            posts.append(data)
            raise TimeoutError('uncertain')
        return original(operation, data)

    client.call = uncertain
    result = run(intake, submit=True)
    assert len(posts) == 1
    assert result['work'][1]['status'] == 'NOT_ATTEMPTED_AFTER_HOLD'

