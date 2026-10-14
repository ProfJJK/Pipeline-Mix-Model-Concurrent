"""Read public benchmark data into a source-evidence snapshot; never run models.

No JavaScript is executed. Parse JSON strings in the public page's hydration
stream. A layout change yields no observations rather than invented scores.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


def public_models(raw):
    chunks = []
    for item in re.findall(r'self\.__next_f\.push\((\[.*?\])\)</script>', raw):
        try:
            data = json.loads(item)
            if len(data) == 2 and data[0] == 1 and isinstance(data[1], str):
                chunks.append(data[1])
        except (ValueError, TypeError):
            continue
    models = {}

    def visit(value):
        if isinstance(value, dict):
            if 'intelligenceIndexEvaluations' in value:
                key = value.get('slug') or value.get('id')
                if key:
                    prior = models.get(str(key), {})
                    if len(value['intelligenceIndexEvaluations']) >= len(prior.get('intelligenceIndexEvaluations', [])):
                        models[str(key)] = value
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for line in ''.join(chunks).splitlines():
        _, _, body = line.partition(':')
        try:
            visit(json.loads(body))
        except (ValueError, TypeError):
            continue
    return models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'https://artificialanalysis\.ai/models/[a-z0-9/-]+', args.url):
        parser.error('Only literal public Artificial Analysis model pages are accepted')
    with urlopen(Request(args.url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25) as response:
        if not response.url.startswith('https://artificialanalysis.ai/'):
            raise ValueError('Unexpected benchmark source redirect')
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError('Benchmark page exceeds bound')
    models = public_models(raw.decode('utf-8'))
    if not models:
        raise ValueError('Public page exposed no parseable benchmark records')
    result = dict(schema='cochem-public-benchmark-observation/1', url=args.url,
        retrieved_utc=datetime.now(timezone.utc).isoformat(),
        page_sha256=hashlib.sha256(raw).hexdigest(), models=models,
        host_accepted=False)
    # Evidence snapshots are append-only; caller chooses a fresh output name.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(output=str(args.output), model_count=len(models),
                          model_keys=list(models)[:8])))


if __name__ == '__main__':
    main()
