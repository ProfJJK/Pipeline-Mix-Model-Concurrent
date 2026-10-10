"""Measure ctypes type retention and private-commit growth of ``_commit`` probes.

Read-only native counter experiment. Each variant runs in its own fresh ``python -I``
process so retained types cannot leak between measurements. ``--source`` points at a
``resource_telemetry.py`` file; ``--label`` names the variant in the report. No pipeline
runtime, configuration, database, credential or provider state is touched.

Usage (from the repository root, inside the pipeline venv):

    python -I docs/evidence/windows-2026-10-09/telemetry-repair/measure_commit_probe_retention.py \
        --source src/cochem_pipeline/resource_telemetry.py --label repaired --probes 3000
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import importlib.util
import json
import os
import sys
import tracemalloc

import psutil


def snapshot(calls: int) -> dict[str, int]:
    gc.collect()
    memory = psutil.Process().memory_info()
    current, peak = tracemalloc.get_traced_memory()
    cache = getattr(ctypes, "_pointer_type_cache", {})
    return {
        "calls": calls,
        "pointer_cache_entries": len(cache),
        "performance_type_entries": sum(getattr(key, "__name__", "") == "PerformanceInformation" for key in cache),
        "python_traced_current_bytes": current,
        "python_traced_peak_bytes": peak,
        "rss_bytes": memory.rss,
        "private_bytes": memory.private,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--probes", type=int, default=3000)
    args = parser.parse_args()
    if os.name != "nt":
        print(json.dumps({"label": args.label, "skipped": "Windows native commit accounting only"}))
        return 0
    raw = open(args.source, "rb").read()
    spec = importlib.util.spec_from_file_location("isolated_resource_telemetry", args.source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    tracemalloc.start()
    samples = [snapshot(0)]
    schema = None
    batches = 3
    per_batch = max(1, args.probes // batches)
    for batch in range(batches):
        for _ in range(per_batch):
            result = module._commit()
            assert result["available"] is True, result["error"]
            assert result["process_memory_available"] is True, result["process_memory_error"]
            assert 0 <= result["total_mb"] <= result["limit_mb"]
            assert abs(result["free_mb"] + result["total_mb"] - result["limit_mb"]) < 1e-8
            keys = sorted(result)
            schema = keys if schema is None else schema
            assert keys == schema
        del result
        samples.append(snapshot((batch + 1) * per_batch))
    first, last = samples[0], samples[-1]
    print(json.dumps({
        "label": args.label,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "python_version": sys.version,
        "native_counter_reads": per_batch * batches,
        "schema_keys": schema,
        "samples": samples,
        "retained_performance_types_delta": last["performance_type_entries"] - first["performance_type_entries"],
        "private_growth_bytes": last["private_bytes"] - first["private_bytes"],
        "rss_growth_bytes": last["rss_bytes"] - first["rss_bytes"],
        "production_runtime_started": False,
        "production_state_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
