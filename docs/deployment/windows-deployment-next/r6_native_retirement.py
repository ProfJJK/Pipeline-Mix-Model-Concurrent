"""Owner-pinned native acceptance amendment for the installed, immutable R6.

The owner withdrew Gemini Pro on 2026-10-12. Preserve the original configuration,
skip that one retired target without executing it, and probe every remaining
selector through the installed production runner. No substitute or accepted
receipt is manufactured. This one-shot process does not change the installation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
from pathlib import Path
import types

MANIFEST = 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4'
CANDIDATE = 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
DECISION = 'owner-2026-10-12-pro-retired'
TARGET = dict(provider='gemini', model='gemini-3.1-pro', reasoning_effort='high')


def retire_plan(plan):
    from cochem_pipeline.native_acceptance_plan import digest
    if (plan.get('schema') != 'cochem-r6-native-acceptance-plan/1'
            or len(plan.get('targets', [])) != 27
            or plan.get('max_execution_slots') != 4
            or plan.get('preparation_status') != 'COMMAND_TEMPLATES_VALID'
            or plan.get('plan_sha256') != digest({key: value for key, value in plan.items() if key != 'plan_sha256'})):
        raise ValueError('Retirement requires the original complete R6 acceptance plan')
    removed = [row for row in plan['targets'] if row['provider'] == 'gemini'
               and row['model'] == 'gemini-3.1-pro']
    if (len(removed) != 1 or any(removed[0][key] != value for key, value in TARGET.items())
            or removed[0]['route_positions'] != [dict(tier=5, choice=3), dict(tier=6, choice=3)]):
        raise ValueError('Only the exact owner-retired Pro High fallback may be omitted')
    value = copy.deepcopy(plan)
    value['targets'] = [row for row in value['targets'] if (row['provider'], row['model']) != ('gemini', 'gemini-3.1-pro')]
    value['owner_retirement'] = dict(schema='cochem-owner-model-retirement/1', decision=DECISION, original_plan_sha256=plan['plan_sha256'],
        retired_target=dict(TARGET), retired_status='OWNER_RETIRED_MODEL_NOT_PROBED',
        retired_model_jobs_executed=0, replacement_selected=False)
    value.pop('plan_sha256')
    value['plan_sha256'] = digest(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('output', 'manifest-hash', 'candidate-hash'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--custody-sha256')
    args = parser.parse_args()
    if (args.manifest_hash, args.candidate_hash) != (MANIFEST, CANDIDATE):
        raise ValueError('Retirement is restricted to the exact installed R6')
    from cochem_pipeline import r6_native_acceptance as native
    from cochem_pipeline import r6_host_acceptance as host
    custody = None
    if args.custody_sha256:
        from cochem_pipeline import windows as win
        path = Path(__file__).with_name('r6_custody_amendment.py')
        raw = host.read_bound(win, path, args.custody_sha256, 65536)
        helper = types.ModuleType('r6_custody_amendment')
        helper.__file__ = str(path)
        exec(compile(raw, str(path), 'exec'), helper.__dict__)
        custody = helper.install(args.custody_sha256)
    original_plan, original_run = native.build_plan, native.run_probes
    plans = []
    def build(candidate):
        plan = retire_plan(original_plan(candidate))
        plans.append(plan)
        return plan
    def run(*args, **kwargs):
        result = original_run(*args, **kwargs)
        if (len(plans) != 1 or result['count'] != 26 or len(result['targets']) != 26
                or any((row['provider'], row['model']) == ('gemini', TARGET['model']) for row in result['targets'])):
            raise ValueError('Retirement selector coverage differs')
        result['owner_retirement'] = dict(plans[0]['owner_retirement'],
            helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        if custody is not None:
            result['agent_custody_amendment'] = custody
        return result
    # Only this private one-shot process changes callbacks. host.run still
    # verifies SYSTEM, exact interpreter, manifest, candidate and installed tree.
    native.build_plan, native.run_probes = build, run
    try:
        host.run('native', args.output, args.manifest_hash, args.candidate_hash)
    except Exception as error:
        if custody is not None:
            helper.save_failure(error, args.output)
        raise
    finally:
        native.build_plan, native.run_probes = original_plan, original_run


if __name__ == '__main__':
    main()
