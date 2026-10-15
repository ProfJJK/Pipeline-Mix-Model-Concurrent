"""Inspect/submit only a pinned reviewed useful-work selection, never bulk import.

Default is authenticated read-only inspection. --submit is the only POST opt-in.
Use the same durable ledger on every invocation. Never delete a reservation to
retry. Controller identity binding comes from the separately verified deployment
receipt and health inspection; this script does not infer deployment success.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from cochem_pipeline.backlog_intake_428 import load_selected_work, run_selected_intake
from cochem_pipeline.backlog_recovery_428 import SubmissionLedger, _json, _pinned_bytes
from cochem_pipeline.ramdisk import ordinary_tree
from cochem_supervisor.probes import ControllerClient


def _save(path, report):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('selection', 'plan', 'controller-binding', 'client-config'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--submit', action='store_true')
    args = parser.parse_args(argv)
    destination = args.destination
    if not destination.is_absolute() or destination.exists():
        parser.error('--destination must name a new absolute evidence directory')
    ordinary_tree(destination.parent)
    destination.mkdir()
    result = dict(schema='cochem-backlog-intake-result/1', status='INCOMPLETE_PRESERVE_LEDGER',
                  automatic_post_retry=False, completion_verified=False, source_writes=0, deletions=0)
    _save(destination / 'started.json', result)
    try:
        selection, plan = load_selected_work(args.selection, args.selection_sha256, args.plan, args.plan_sha256)
        binding = _json(_pinned_bytes(args.controller_binding, args.controller_binding_sha256, maximum=16384))
        config = _json(_pinned_bytes(args.client_config, args.client_config_sha256, maximum=65536))
        token_file = config.get('token_file')
        if not isinstance(token_file, str) or not Path(token_file).is_absolute():
            raise ValueError('Client config must reference its existing absolute private token file')
        if not args.ledger.is_absolute():
            raise ValueError('The shared durable ledger path must be absolute')
        client = ControllerClient(config.get('port', 47824), token_file)
        ledger = SubmissionLedger(args.ledger)
        result = run_selected_intake(client, ledger, selection, plan,
                                     expected_controller=binding, submit=args.submit)
        result['input_file_pins'] = {name: getattr(args, name + '_sha256')
                                    for name in ('selection', 'plan', 'controller_binding', 'client_config')}
    except Exception as error:
        # Errors may contain source paths, HTTP bodies, or private data. Preserve
        # only the type; the original inputs/ledger remain available for review.
        result.update(status='HELD_PRESERVE_EVIDENCE', error_type=type(error).__name__)
    finally:
        _save(destination / 'result.json', result)
    print(json.dumps(dict(result, report_path=str(destination / 'result.json')), sort_keys=True))
    return 0 if result['status'] in ('READY_NO_SUBMISSION', 'SUBMITTED_OR_RECONCILED') else 2


if __name__ == '__main__':
    raise SystemExit(main())
