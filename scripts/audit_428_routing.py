"""Compile local public-source observations and a reproducible routing audit."""
from __future__ import annotations

import json
from pathlib import Path

from cochem_pipeline.task_routing import (
    audit_owner_matrix, build_gap_resolution_packet, compile_matrix, digest,
    select_reviewers, select_candidates, with_five_model_rows,
)

BENCHMARKS = {
    'aa-briefcase': 'AGT-PROJ', 'gdpval-aa': 'AGT-DELIV',
    'automationbench-aa': 'AGT-AUTO', 'terminalbench-4-0': 'COD-TERM',
    'scicode': 'COD-SCI', 'humanitys-last-exam': 'SCI-FRONT', 'critpt': 'SCI-FORMAL',
    'omniscience': 'GEN-FACT', 'gdp-pdf': 'GEN-DOC',
    'artificial-analysis-long-context-reasoning': 'GEN-LCR',
}


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def main():
    root = Path(__file__).resolve().parents[1] / 'docs/4.2.8'
    owner = json.loads((root / 'references/owner-model-matrix.json').read_text(encoding='utf-8-sig'))
    candidate = compile_matrix(owner)
    observations = dict(schema='cochem-task-benchmark-observations/1', models={}, missing=[])
    sources = [json.loads(path.read_text(encoding='utf-8'))
               for path in sorted((root / 'references').glob('aa-*.json'))]
    mismatches = []
    for key, model in candidate['models'].items():
        slug = model['model'].replace('.', '-')
        if model['effort'] not in (None, 'max') and not (
                model['provider'] == 'gemini' and model['effort'] == 'high'):
            slug += '-' + model['effort']
        found = [(source, source['models'][slug]) for source in sources if slug in source['models']]
        if not found:
            observations['missing'].append(key)
            continue
        # Prefer the matching release page; otherwise retain the exact page provenance.
        source, observed = next((x for x in found if x[0]['url'].endswith('/releases/' + model['model'].replace('.', '-'))), found[0])
        values = {row['slug']: row['score'] for row in observed['intelligenceIndexEvaluations']}
        if any(values.get(name) is None for name in BENCHMARKS) or observed['intelligenceIndexIsEstimated']:
            observations['missing'].append(key)
            continue
        scores = {'GEN-DEFAULT': observed['intelligenceIndex']}
        for benchmark, tag in BENCHMARKS.items():
            scores[tag] = values[benchmark] * (1 if tag in ('AGT-PROJ', 'AGT-DELIV', 'GEN-FACT') else 100)
        cost = observed.get('intelligenceIndexCostPerTask')
        cost = cost.get('cost', {}).get('total') if isinstance(cost, dict) else None
        record = dict(family=model['family'], effort=model['effort'], name=observed['name'],
            estimated=observed['intelligenceIndexIsEstimated'], scores=scores,
            context_limit=observed['contextWindowTokens'], cost_per_task=cost,
            url=source['url'], page_sha256=source['page_sha256'], retrieved_utc=source['retrieved_utc'])
        observations['models'][key] = record
        for tag, value in scores.items():
            old = owner['models'][key]['scores'][tag]
            # Differences within the displayed whole-unit rounding are not defects.
            if abs(old - value) > 0.51:
                mismatches.append(dict(model_id=key, task_type=tag, supplied=old,
                    observed=value, source=source['url']))
    catalog = with_five_model_rows(compile_matrix(owner, observations))
    decision_packet = build_gap_resolution_packet(owner, observations)
    report = audit_owner_matrix(owner)
    report.update(benchmark_mismatches=mismatches, observed_models=len(observations['models']),
        missing_published_effort_results=observations['missing'],
        corrected_catalog_sha256=digest(catalog), routing_gaps=[], reviewer_gaps=[])
    table = ['# Audited 4.2.8 routing candidate', '',
        'Publisher scores replace the supplied estimates. CLI availability and quota are separate.',
        'No below-floor fallback is permitted. Empty rows require a policy decision or new evidence.',
        'Argon Low/Medium are proposed profiles; absent benchmark results are not interpolated.', '',
        'Five ranked profiles are shown per row. Tiers 1–7 rank qualifying profiles by lowest reference cost,',
        'then performance; tiers 8–10 rank by strongest measured performance, then cost.',
        'Tier 10 uses maximum effort. The PDFs allow effort variants in slots 4–5; reviews still require a different underlying model.',
        'Each cell gives model/profile · benchmark score · reference cost/task. **HELD** means below the floor.',
        'These reference costs are benchmark API evaluation costs, not subscription quota charges.', '',
        '| Task type | Tier | Floor | 1 | 2 | 3 | 4 | 5 |',
        '| --- | ---: | ---: | --- | --- | --- | --- | --- |']
    for tag, spec in catalog['task_types'].items():
        for tier, row in spec['tiers'].items():
            eligible = select_candidates(catalog, [tag], int(tier))
            gaps = [key for key in eligible if not select_reviewers(catalog, [tag], int(tier), key)]
            if not eligible:
                report['routing_gaps'].append(dict(task_type=tag, tier=int(tier), floor=row['floor']))
            for key in gaps:
                report['reviewer_gaps'].append(dict(task_type=tag, tier=int(tier), producer=key))
            cells = []
            for option in row['ranked_options']:
                key = option['model_id']
                cost = option['reference_cost_per_task']
                cell = f"{catalog['models'][key]['name']} · {option['scores'][tag]:.2f} · " + (f'${cost:.4f}' if cost is not None else 'cost unavailable')
                cells.append(cell + (' **HELD**' if not option['meets_floor'] else ''))
            table.append(f"| {tag} | {tier} | {row['floor']} | " + ' | '.join(cells) + ' |')
    write(root / 'benchmark-observations.json', observations)
    write(root / 'routing-audit.json', report)
    write(root / 'routing-candidate.json', catalog)
    write(root / 'routing-decision-packet.json', decision_packet)
    (root / 'ROUTING_MATRIX.md').write_text('\n'.join(table) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('model_count', 'row_count', 'observed_models',
        'missing_published_effort_results', 'routing_gaps')} | dict(
            mismatches=len(mismatches), findings=len(report['findings']),
            reviewer_gaps=len(report['reviewer_gaps']),
            calibration_changes=len(decision_packet['calibration_changes']),
            decision_packet_sha256=digest(decision_packet))))


if __name__ == '__main__':
    main()

