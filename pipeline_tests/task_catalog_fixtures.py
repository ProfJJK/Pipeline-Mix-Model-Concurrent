"""Inert accepted-catalog fixtures; these receipts are not host acceptance."""
import json
from pathlib import Path

from cochem_pipeline.catalog_journal import initialize, initialize_task_catalog
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_catalog_428 import compile_task_catalog_plan, activate_task_catalog


def accepted_catalog_fixture(policy, catalog=None, **plan_options):
    if catalog is None:
        catalog = json.loads((Path(__file__).parents[1] / 'docs/4.2.8/routing-candidate.json').read_text())
    binaries = {name: {'executable': f'C:/inert-fixture/{name}.exe',
                      'sha256': str(index) * 64, 'version': 'inert-fixture-only'}
                for index, name in enumerate(('codex', 'claude', 'gemini'), 1)}
    plan = compile_task_catalog_plan(policy, catalog, binaries,
                                    expected_policy_digest=policy.digest, **plan_options)
    receipts = [dict(provider=p, model=m, reasoning_effort=e,
                     binary_sha256=plan.binary_bindings[p]['sha256'],
                     status='NATIVE_SELECTOR_ACCEPTED', cleanup_verified=True,
                     plan_digest=plan.digest, request_id='a' * 32,
                     reservation_id=f'inert-{index}', fencing_token=index)
                for index, (p, m, e) in enumerate(sorted(set(plan.required_targets) | {plan.control_target}), 1)]
    return activate_task_catalog(plan, receipts, request_id='a' * 32,
                                 pointer_sha256='b' * 64, proposal_sha256='c' * 64)[0]


def accepted_planning_store(path, catalog=None):
    policy = load_routing_policy({'policy_version': 3})
    accepted = accepted_catalog_fixture(policy, catalog)
    store = JobStore(path, routing_policy=policy)
    with store._connection() as conn:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        initialize(conn, policy)
        initialize_task_catalog(conn, accepted)
        conn.commit()
    store.close()
    return JobStore(path, routing_policy=policy, catalog_enabled=True), accepted
