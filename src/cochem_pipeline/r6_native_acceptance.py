"""Sequential owner-run native acceptance using the production inference runner.

These are disposable protocol probes, not production workflows or coding jobs.
Every target comes from the exact captured Chapter 06 catalog. The acceptance
root contains its own durable reservations/logs; production databases and repair
budgets are never opened. A failed probe is recorded once and not retried.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
import uuid

from .native_acceptance_plan import build_plan, digest
from .routing import validate_selected_route


def make_probe(policy, target, nonce):
    position = target['route_positions'][0]
    score, index = position['tier'], position['choice'] - 1
    selected = policy.candidates(score, 'PREFLIGHT_REQUEST')[index]
    if any(selected.as_dict()[k] != target[k] for k in ('provider', 'model', 'reasoning_effort')):
        raise ValueError('Acceptance target no longer matches the captured catalog')
    route = dict(selected.as_dict(), score=score, tier=policy.tier_for_score(score), candidate_index=index,
        policy_digest=policy.digest, reservation_id='acceptance-' + nonce, attempt_id=nonce,
        fencing_token=1, worker_slot=target['worker'], kind='PREFLIGHT_REQUEST')
    validate_selected_route(policy, route, kind='PREFLIGHT_REQUEST')
    return dict(kind='PREFLIGHT_REQUEST', payload={'objective': 'Verify this exact native model/effort selector.',
        'requirements': ['Return ready true without tools or filesystem changes.']},
        job_id='probe-' + nonce, workflow_id='acceptance-' + nonce, attempt_id=nonce,
        fencing_token=1, worker_slot=target['worker'], route=route, routing_policy=policy.as_dict())


def validate_result(target, output, receipt):
    if output != {'ready': True} or type(output.get('ready')) is not bool:
        raise ValueError('Native acceptance response is not ready true')
    if (receipt.get('provider') != target['provider'] or receipt.get('requested_model') != target['model']
            or receipt.get('requested_effort') != target['reasoning_effort']
            or receipt.get('subscription_verified') is not True or receipt.get('exit_code') != 0
            or receipt.get('worker_slot') != target['worker']):
        raise ValueError('Native acceptance receipt differs from the exact target')
    reported_model, reported_effort = receipt.get('reported_model'), receipt.get('reported_effort')
    if reported_model is not None and reported_model != target['model']:
        raise ValueError('Native model identity contradicts the selected model')
    if reported_effort is not None and reported_effort != target['reasoning_effort']:
        raise ValueError('Native effort contradicts the selected effort')
    if target['provider'] == 'gemini' and (reported_model != target['model']
            or receipt.get('native_reported_model') != target['model'] + '-' + target['reasoning_effort']):
        raise ValueError('Agy did not report the exact routed slug/effort')
    evidence = receipt.get('inference_policy')
    if not isinstance(evidence, dict):
        raise ValueError('Production inference policy evidence is missing')
    return dict(status='NATIVE_SELECTOR_ACCEPTED', model_identity_observed=reported_model is not None,
        actual_effort_observed=reported_effort is not None,
        reported_model=reported_model, reported_effort=reported_effort,
        native_reported_model=receipt.get('native_reported_model'),
        subscription_verified=True, cleanup_verified=True)


def run_probes(config, raw_config, private_root, ram_manager, *, runner_factory=None, clock=time.monotonic):
    """Called only after SYSTEM custody, quiescence, RAM and auth preconditions.

    The production runner closes/validates each owned native tree before return.
    Typed temporary provider unavailability records an unverified target and
    continues independent providers. Other exceptions stop the series. Nothing
    prompts, retries, clears quarantine or substitutes a different target.
    """
    from .worker import NativeRunner
    plan = build_plan(raw_config)
    if plan['preparation_status'] != 'COMMAND_TEMPLATES_VALID':
        raise ValueError('Native acceptance requires all reviewed command templates')
    private_root = Path(private_root)
    # Caller creates and validates this new SYSTEM/BA-only directory.
    if any(private_root.iterdir()):
        raise ValueError('Preserve existing native acceptance outputs')
    runner = (runner_factory or NativeRunner)(replace(config, private_root=private_root, timeout_seconds=60))
    results, unavailable_pools, deadline = [], set(), clock() + 3600
    def write(name, value):
        with (private_root / name).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            import os
            os.fsync(stream.fileno())
    write('plan.json', plan)
    for number, target in enumerate(plan['targets']):
        phase = f'target-{number:02d}'
        row = dict(provider=target['provider'], model=target['model'], effort=target['reasoning_effort'],
            worker=target['worker'], route_positions=target['route_positions'])
        pool = config.routing.as_dict()['provider_limits'][target['provider']]['quota_pool']
        if pool in unavailable_pools:
            row.update(status='NOT_PROBED_POOL_UNAVAILABLE', actual_effort_observed=False)
            write(phase + '-unavailable.json', row)
            results.append(row)
            continue
        try:
            if clock() + 180 > deadline:
                raise TimeoutError('Native acceptance has insufficient remaining time')
            node = make_probe(config.routing, target, uuid.uuid4().hex)
            descriptor = ram_manager.workspace(target['worker'])
            descriptor.validate(identity=config.workers[target['worker']]['name'], cwd=descriptor.root)
            reservation = dict(schema='cochem-r6-disposable-native-reservation/1',
                scope='acceptance_only_not_production_job_board', node=node,
                candidate_sha256=plan['candidate_sha256'], max_parallel_probes=1)
            write(phase + '-reservation.json', reservation)
            output, receipt = runner.run(node, target['worker'], '', lambda: clock() < deadline,
                workspace=descriptor.root, ramdisk_workspace=descriptor)
            row.update(receipt_sha256=digest(receipt), **validate_result(target, output, receipt))
            write(phase + '-verified.json', row)
            results.append(row)
        except Exception as exc:
            from .failures import ProviderFailure
            if isinstance(exc, ProviderFailure) and exc.category in ('quota', 'busy', 'provider'):
                row.update(status='PROVIDER_TEMPORARILY_UNAVAILABLE', category=exc.category,
                    actual_effort_observed=False, cleanup_verified=True)
                write(phase + '-unavailable.json', row)
                results.append(row)
                if exc.hold_scope == 'pool':
                    unavailable_pools.add(pool)
                continue
            write('native-held.json', dict(schema='cochem-r6-native-acceptance/1', status='HELD_PRESERVE_PARTIAL',
                phase=phase, completed=len(results), error_type=type(exc).__name__,
                category=getattr(exc, 'category', None), automatic_retry=False, late_prompt=False,
                activation_ready=False, native_plan_sha256=plan['plan_sha256']))
            raise
    verified = [r for r in results if r['status'] == 'NATIVE_SELECTOR_ACCEPTED']
    covered = {p['tier'] for r in verified for p in r['route_positions']}
    result = dict(schema='cochem-r6-native-acceptance/1', status='ALL_NATIVE_SELECTORS_ACCEPTED' if len(verified) == len(results)
        else 'NATIVE_ACCEPTANCE_PARTIAL_AVAILABILITY',
        candidate_sha256=plan['candidate_sha256'], native_plan_sha256=plan['plan_sha256'],
        targets=results, count=len(results), accepted_count=len(verified),
        tiers_with_verified_route=sorted(covered), tiers_without_verified_route=sorted(set(range(1, 11)) - covered),
        production_workflows_executed=0,
        coding_workflow_acceptance=False, actual_effort_unobserved=sum(not r['actual_effort_observed'] for r in results),
        automatic_retry=False, activation_ready=False)
    write('native-verified.json', result)
    return result
