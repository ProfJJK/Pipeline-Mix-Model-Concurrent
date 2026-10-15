"""Prepare a job's first-response form from the worker's actual output contract.

This pure, offline helper never submits work or changes live configuration. Its
output is a draft form, not evidence that a job or any verification completed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def prepare(node_path: Path, output_path: Path):
    from cochem_pipeline.output_contracts import prepare_output_contract
    from cochem_pipeline.worker import strict_json

    with node_path.open('rb') as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Job input exceeds the bounded offline preparation size')
    node = strict_json(raw.decode('utf-8'))
    if not isinstance(node, dict) or not isinstance(node.get('payload'), dict):
        raise ValueError('Input must be one captured execution node with kind and payload')
    contract = prepare_output_contract(node)
    result = {key: contract[key] for key in
              ('schema', 'kind', 'contract_sha256', 'output_schema', 'handoff', 'instruction')}
    # Exclusive creation preserves any prior handoff, completed result or evidence.
    with output_path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return {'status': 'HANDOFF_FORM_PREPARED_NOT_EXECUTED', 'path': str(output_path),
            'contract_sha256': contract['contract_sha256'], 'providers_executed': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    # Bind the offline helper to this checkout, not an unrelated editable install.
    source = Path(__file__).resolve().parents[1] / 'src'
    sys.path.insert(0, str(source))
    print(json.dumps(prepare(args.node, args.output), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
