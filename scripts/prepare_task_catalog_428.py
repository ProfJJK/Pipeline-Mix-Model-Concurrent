"""Freeze a fresh offline task-catalog acceptance request; never execute providers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cochem_pipeline.routing import _strict_json, load_routing_policy
from cochem_pipeline.task_catalog_acceptance_428 import encoded, execution_bindings, prepare_request
from prepare_428_release import _assert_fresh_destination


def prepare_task_catalog_release(destination, *, configuration, catalog, binary_bindings,
                                 request_id, source_commit, previous_task_catalog=None,
                                 allow_partial_publication=False, candidate_profile_ids=None):
    """Return immutable request pins for the consolidated owner installer."""
    import re
    if not isinstance(source_commit,str) or not re.fullmatch('[0-9a-f]{40}',source_commit):
        raise ValueError('Task catalog release requires the exact source commit')
    if configuration.get('max_execution_slots') != 4:
        raise ValueError('Task catalog acceptance must preserve four execution slots')
    request=prepare_request(load_routing_policy(configuration['routing']), catalog, binary_bindings,
        request_id=request_id, execution_bindings=execution_bindings(configuration['providers'],configuration['workers']),
        previous_task_catalog=previous_task_catalog,allow_partial_publication=allow_partial_publication,
        candidate_profile_ids=candidate_profile_ids)
    data=encoded(request)
    destination=_assert_fresh_destination(Path(destination))
    destination.mkdir()
    with (destination/'task-catalog-request.json').open('xb') as stream:
        stream.write(data)
    manifest=dict(schema='cochem-task-catalog-release/4.2.8',source_commit=source_commit,
        request_id=request_id,request_sha256=hashlib.sha256(data).hexdigest(),request_bytes=len(data),
        configuration_sha256=hashlib.sha256(encoded(configuration)).hexdigest(),
        candidate_profile_ids=request['candidate_profile_ids'],
        allow_partial_publication=allow_partial_publication,
        activation_authorized=False,native_probes_executed=0,planning_enabled=False)
    with (destination/'task-catalog-manifest.json').open('xb') as stream:
        stream.write(encoded(manifest))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('configuration','catalog','binary-bindings','destination','request-id','source-commit'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--previous-task-catalog')
    parser.add_argument('--candidate-profile-ids',help='JSON array of profiles with reviewed native bindings; other rankings are retained without acceptance')
    parser.add_argument('--allow-partial-publication',action='store_true')
    args=parser.parse_args()
    def read(path):
        with Path(path).open('rb') as stream:
            data=stream.read(4*1024*1024+1)
        if not 1<=len(data)<=4*1024*1024:
            raise ValueError('Preparation input exceeds its bound')
        return _strict_json(data.decode('utf-8'))
    result=prepare_task_catalog_release(args.destination,configuration=read(args.configuration),
        catalog=read(args.catalog),binary_bindings=read(args.binary_bindings),
        request_id=args.request_id,source_commit=args.source_commit,
        previous_task_catalog=read(args.previous_task_catalog) if args.previous_task_catalog else None,
        candidate_profile_ids=read(args.candidate_profile_ids) if args.candidate_profile_ids else None,
        allow_partial_publication=args.allow_partial_publication)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
