"""Explicit, protected R6 startup amendment for the owner's retired Pro route.

The installed R6 and historical captured policies remain immutable. This small
entry point removes the withdrawn identity from candidate selection and from
the production runner's is_enabled check, including old captured jobs. It is
not R7 hot catalog activation. Its hash is part of the scheduled task action.
Importing this file neither starts the daemon nor installs the amendment.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import types

ROOT = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r6-v1')
CANDIDATE = 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
RETIRED = frozenset(('gemini-3.1-pro', 'gemini-3.1-pro-preview'))


def apply_retirement(policy_class, routing_store=None):
    """Keep every survivor and its order; no provider or effort substitution."""
    if '_r6_owner_retirement' in policy_class.__dict__:
        raise ValueError('Retirement amendment was already installed')
    original = policy_class.candidates

    def candidates(self, score, kind='CHAPTER_DRAFT'):
        values = original(self, score, kind)
        # Earlier policies can put Pro before a surviving target. Preserve those
        # captured indices; the admission filter below skips the retired row.
        if self.as_dict()['policy_version'] != 3:
            return values
        return tuple(target for target in values
                     if not (target.provider == 'gemini' and target.model in RETIRED))

    policy_class.candidates = candidates
    policy_class._r6_owner_retirement = original
    if routing_store is not None:
        original_admission = routing_store._candidate_unavailability

        def available(conn, job, state, target, current_policy, now):
            if target.get('provider') == 'gemini' and target.get('model') in RETIRED:
                return 'retired_target'
            return original_admission(conn, job, state, target, current_policy, now)

        routing_store._candidate_unavailability = available
    return original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guard-sha256', required=True)
    parser.add_argument('--custody-sha256')
    parser.add_argument('--config', required=True)
    parser.add_argument('--queue-launch-output-root', required=True)
    parser.add_argument('--docker-wait-seconds', type=int, required=True)
    args = parser.parse_args()
    from cochem_pipeline import windows as win
    win.require_system()
    if (Path(sys.prefix) != ROOT / '.venv' or
            Path(sys.executable) != ROOT / '.venv/Scripts/python.exe' or
            Path(args.config) != ROOT / 'pipeline.json' or args.docker_wait_seconds != 900):
        raise ValueError('Retirement amendment requires the exact installed R6')
    from cochem_pipeline.r6_host_acceptance import read_bound
    # The task pins this separate protected entry point; never weaken or rewrite
    # the installed revision checks to make the supplemental binding disappear.
    read_bound(win, Path(__file__), args.guard_sha256, 65536)
    read_bound(win, Path(args.config), CANDIDATE)
    if args.custody_sha256:
        path = Path(__file__).with_name('r6_custody_amendment.py')
        raw = read_bound(win, path, args.custody_sha256, 65536)
        helper = types.ModuleType('r6_custody_amendment')
        helper.__file__ = str(path)
        exec(compile(raw, str(path), 'exec'), helper.__dict__)
        helper.install(args.custody_sha256, registry=True)
    from cochem_pipeline.routing import RoutingPolicy
    from cochem_pipeline import routing_store
    apply_retirement(RoutingPolicy, routing_store)
    from cochem_pipeline.__main__ import daemon
    daemon(args.config, queue_launch_output_root=args.queue_launch_output_root,
           docker_wait_seconds=args.docker_wait_seconds)


if __name__ == '__main__':
    main()
