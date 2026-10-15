"""Bounded transport for reviewed existing work, separate from installation.

Only exact selected requests from a pinned recovery plan are accepted. A durable
reservation precedes the sole POST; any uncertain outcome is reconciled by an
authenticated exact-ID lookup. Neither absence nor a timeout permits a retry.
"""
from __future__ import annotations

import math
from pathlib import Path

from cochem_supervisor.probes import ControllerHttpError
from .backlog_recovery_428 import _json, _pinned_bytes, digest, validate_prepared_request

_BINDING_FIELDS = ('version', 'instance_id', 'pid', 'process_started_at', 'source_root')
_ALLOWED_CATEGORIES = {'quick_reference', 'consensus_extract', 'target_evaluation', 'improvement'}


class IntakeHold(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def validate_selection(selection, plan):
    if (not isinstance(plan, dict) or plan.get('schema') != 'cochem-legacy-recovery-plan/1'
            or not isinstance(selection, dict)
            or set(selection) != {'schema', 'plan_sha256', 'work', 'submitted', 'completion_requires'}
            or selection['schema'] != 'cochem-useful-work-acceptance-selection/1'
            or selection['plan_sha256'] != digest(plan) or selection['submitted'] is not False
            or selection['completion_requires'] != ['terminal_receipt', 'actual_deliverables', 'independent_checks']
            or not isinstance(selection['work'], list) or not 1 <= len(selection['work']) <= 3):
        raise IntakeHold('SELECTION_OR_PLAN_INVALID')
    seen = set()
    candidates = plan.get('queue_candidates')
    if not isinstance(candidates, list):
        raise IntakeHold('SELECTION_OR_PLAN_INVALID')
    for row in selection['work']:
        if (not isinstance(row, dict) or row.get('category') not in _ALLOWED_CATEGORIES
                or row.get('status') != 'READY_FOR_REVIEWED_INTAKE' or row.get('holds')
                or sum(candidate == row for candidate in candidates) != 1):
            raise IntakeHold('SELECTION_NOT_EXACT_REVIEWED_WORK')
        request = row['prepared_request']
        validate_prepared_request(request)
        task_id = request['body']['task_id']
        if task_id in seen:
            raise IntakeHold('DUPLICATE_SELECTED_IDENTITY')
        seen.add(task_id)
        if request['body'].get('project_id') != request['identity'].get('project_id'):
            raise IntakeHold('PROJECT_IDENTITY_MISMATCH')
        aliases = row.get('aliases')
        if (not isinstance(aliases, list) or not aliases
                or row['reference'] not in [alias.get('reference') for alias in aliases]):
            raise IntakeHold('EXACT_LEGACY_ALIASES_REQUIRED')


def load_selected_work(selection_path, selection_sha256, plan_path, plan_sha256):
    selection = _json(_pinned_bytes(selection_path, selection_sha256, maximum=4 * 1024 * 1024))
    plan = _json(_pinned_bytes(plan_path, plan_sha256, maximum=32 * 1024 * 1024))
    validate_selection(selection, plan)
    return selection, plan


def _health(client, expected):
    if (not isinstance(expected, dict) or set(expected) != {'schema', *_BINDING_FIELDS}
            or expected['schema'] != 'cochem-backlog-controller-binding/1'
            or expected['version'] != '4.2.8'
            or not isinstance(expected['instance_id'], str) or not 1 <= len(expected['instance_id']) <= 128
            or type(expected['pid']) is not int or expected['pid'] <= 0
            or type(expected['process_started_at']) not in (int, float)
            or not math.isfinite(expected['process_started_at']) or expected['process_started_at'] <= 0
            or not isinstance(expected['source_root'], str) or not Path(expected['source_root']).is_absolute()):
        raise IntakeHold('CONTROLLER_BINDING_INVALID')
    health = client.call('/health')
    if any(health.get(key) != expected[key] for key in _BINDING_FIELDS):
        raise IntakeHold('CONTROLLER_IDENTITY_CHANGED')
    planning = health.get('task_planning') or {}
    if (health.get('service_identity') != 'SYSTEM' or health.get('trip_errors')
            or planning.get('status') != 'ENABLED' or planning.get('execution_materialization') != 'CONNECTED'):
        raise IntakeHold('PLANNING_NOT_READY')
    return health


def _lookup(client, request):
    try:
        response = client.call('/tasks/status/' + request['body']['task_id'])
    except ControllerHttpError as error:
        if error.status == 404 and error.error_code == 'TASK_NOT_FOUND':
            return None
        raise
    _matches(response, request)
    return response


def _matches(response, request):
    body = request['body']
    task = response.get('task') if isinstance(response, dict) else None
    if (not isinstance(task, dict) or response.get('task_id') != body['task_id']
            or response.get('workflow_id') != body['task_id'] or task.get('task_id') != body['task_id']
            or task.get('objective') != body['objective'] or task.get('project_id') != body.get('project_id')
            or task.get('requested_requirements', []) != []):
        raise IntakeHold('TASK_IDENTITY_MISMATCH')


def _receipt(request):
    # Only immutable identity is receipted. Mutable progress/time and a later
    # controller restart cannot alter the identity of an already accepted task.
    return digest(dict(schema='cochem-backlog-accepted-identity/1', task_id=request['body']['task_id'],
                       request_sha256=digest(request), objective_sha256=digest(request['body']['objective']),
                       project_id=request['body'].get('project_id')))


def _safe_error(error):
    result = {'error_type': type(error).__name__}
    if isinstance(error, IntakeHold):
        result['reason'] = error.reason
    elif isinstance(error, ControllerHttpError):
        result.update(reason='CONTROLLER_HTTP_ERROR', http_status=error.status)
    else:
        result['reason'] = 'INPUT_OR_TRANSPORT_HOLD'
    return result


def run_selected_intake(client, ledger, selection, plan, *, expected_controller, submit=False):
    """Inspect by default; explicit submit sends at most one POST per reserved ID.

    Reports contain identities/digests/categories, never objectives, source text,
    bearer tokens, or untrusted exception/HTTP bodies. Acceptance is not completion.
    """
    result = dict(schema='cochem-backlog-intake-result/1', status='HELD_PRESERVE_EVIDENCE', work=[],
                  post_attempts=0, automatic_post_retry=False, completion_verified=False,
                  source_writes=0, deletions=0)
    try:
        if type(submit) is not bool:
            raise IntakeHold('EXPLICIT_SUBMISSION_FLAG_REQUIRED')
        validate_selection(selection, plan)
        _health(client, expected_controller)
        projects = client.call('/coding/projects')
        if (not isinstance(projects.get('projects'), list)
                or any(not isinstance(project, str) for project in projects['projects'])):
            raise IntakeHold('PROJECT_REGISTRY_UNVERIFIED')
        for row in selection['work']:
            project = row['prepared_request']['body'].get('project_id')
            if project is not None and project not in projects['projects']:
                raise IntakeHold('EXACT_PROJECT_NOT_REGISTERED')
        result.update(plan_sha256=digest(plan), selection_sha256=digest(selection),
                      controller_binding_sha256=digest(expected_controller))
        held = False
        for row in selection['work']:
            request = row['prepared_request']
            item = dict(task_id=request['body']['task_id'], request_sha256=digest(request),
                        reference=row['reference'], status='NOT_ATTEMPTED_AFTER_HOLD')
            result['work'].append(item)
            if held:
                continue
            try:
                _health(client, expected_controller)
                existing = _lookup(client, request)
                if not submit:
                    item['status'] = 'EXISTING_MATCH' if existing is not None else 'READY_READ_ONLY'
                    continue
                reservation = ledger.reserve(request, plan_sha256=digest(plan),
                    references=sorted(alias['reference'] for alias in row['aliases']))
                if existing is not None:
                    ledger.mark_submitted(item['task_id'], item['task_id'], receipt_sha256=_receipt(request))
                    item['status'] = 'RECONCILED'
                    continue
                if not reservation['may_submit']:
                    raise IntakeHold('RESERVED_TASK_NOT_FOUND')
                # Recheck immediately before the single write. Any interruption
                # after reservation remains reserved, even if no POST was sent.
                validate_prepared_request(request)
                _health(client, expected_controller)
                validate_prepared_request(request)
                result['post_attempts'] += 1
                try:
                    response = client.call('/tasks/submit', request['body'])
                    _matches(response, request)
                except Exception:
                    # The request may already have committed. Never POST again.
                    _health(client, expected_controller)
                    if _lookup(client, request) is None:
                        raise IntakeHold('UNCERTAIN_SUBMISSION') from None
                    item['status'] = 'RECONCILED_AFTER_UNCERTAIN_POST'
                else:
                    _health(client, expected_controller)
                    if _lookup(client, request) is None:
                        raise IntakeHold('ACKNOWLEDGEMENT_NOT_DURABLE')
                    item['status'] = 'SUBMITTED'
                ledger.mark_submitted(item['task_id'], item['task_id'], receipt_sha256=_receipt(request))
            except Exception as error:
                item.update(status='HELD', **_safe_error(error))
                held = True
        result['status'] = ('HELD_PRESERVE_EVIDENCE' if held else
                            'SUBMITTED_OR_RECONCILED' if submit else 'READY_NO_SUBMISSION')
    except Exception as error:
        result.update(_safe_error(error))
    return result
