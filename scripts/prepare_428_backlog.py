"""Prepare a new read-only legacy backlog review package; never submit or delete.

Source specification: {"schema":"cochem-legacy-source-spec/1","sources":
[{"path":"absolute.db","role":"kanban|exam_evidence|v412|youtube|layer1"}]}.
Destination must not exist. Whole database backups and private inventory are
retained there. Only aggregate counts and hashes are printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

# Select this checkout under isolated Python, without ambient PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from cochem_pipeline.backlog_recovery_428 import (
    _json, build_recovery_plan, digest, inventory_snapshots, select_acceptance_work,
)
from scripts.backup_legacy_windows_state import snapshot_databases


def prepare(source_spec, destination, *, resolutions=None):
    if (not isinstance(source_spec, dict) or set(source_spec) != {'schema', 'sources'} or
            source_spec['schema'] != 'cochem-legacy-source-spec/1' or
            not isinstance(source_spec['sources'], list) or not 1 <= len(source_spec['sources']) <= 32):
        raise ValueError('Expected an explicit bounded legacy source specification')
    roles = {}
    for item in source_spec['sources']:
        if not isinstance(item, dict) or set(item) != {'path', 'role'}:
            raise ValueError('Each source needs an exact path and role')
        source = Path(item['path'])
        if not source.is_absolute():
            raise ValueError('Source path must be absolute')
        resolved = str(source.resolve(strict=True))
        if resolved in roles:
            raise ValueError('Duplicate legacy source')
        if item['role'] not in {'kanban', 'exam_evidence', 'v412', 'youtube', 'layer1'}:
            raise ValueError('Unknown source role')
        roles[resolved] = item['role']
    destination = Path(destination)
    if not destination.is_absolute() or destination.exists():
        raise ValueError('Destination must be a new absolute private directory')
    destination.mkdir()
    report = {'schema': 'cochem-legacy-preparation-result/1', 'status': 'INCOMPLETE_PRESERVED',
              'source_spec_sha256': digest(source_spec), 'source_writes': 0,
              'controller_writes': 0, 'submissions': 0, 'deletions': 0}
    try:
        snapshot_databases([Path(path) for path in roles], destination / 'snapshots')
        manifest = destination / 'snapshots/snapshot-manifest.json'
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        inventory = inventory_snapshots(manifest, manifest_sha256, roles)
        plan = build_recovery_plan(inventory, resolutions)
        acceptance = select_acceptance_work(plan)
        pins = {}
        for name, value in [('source-spec.json', source_spec), ('inventory.json', inventory),
                            ('recovery-plan.json', plan), ('acceptance-selection.json', acceptance)]:
            path = destination / name
            with path.open('x', encoding='utf-8', newline='\n') as output:
                output.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
            pins[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        report.update(status='PREPARED_NO_SUBMISSION_OR_DELETION', pins=pins,
                      snapshot_manifest_sha256=manifest_sha256,
                      inventory_counts=inventory['counts'],
                      deletion_review_counts=plan['deletion_manifest']['counts'],
                      queue_review_count=len(plan['queue_candidates']),
                      ready_acceptance_count=len(acceptance['work']))
    except Exception as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        with (destination / 'preparation-result.json').open('x', encoding='utf-8') as output:
            output.write(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-spec', required=True, type=Path)
    parser.add_argument('--source-spec-sha256', required=True)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--resolutions', type=Path)
    parser.add_argument('--resolutions-sha256')
    args = parser.parse_args()
    from cochem_pipeline.backlog_recovery_428 import _pinned_bytes
    source_spec = _json(_pinned_bytes(args.source_spec, args.source_spec_sha256, maximum=1024 * 1024))
    if bool(args.resolutions) != bool(args.resolutions_sha256):
        parser.error('--resolutions and --resolutions-sha256 must be supplied together')
    resolutions = None if args.resolutions is None else _json(
        _pinned_bytes(args.resolutions, args.resolutions_sha256, maximum=16 * 1024 * 1024))
    result = prepare(source_spec, args.destination, resolutions=resolutions)
    print(json.dumps(dict(result, report_path=str(args.destination / 'preparation-result.json')), sort_keys=True))


if __name__ == '__main__':
    main()
