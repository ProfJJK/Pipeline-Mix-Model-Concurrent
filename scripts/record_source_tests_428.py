"""Run the serialized source tests for the exact committed tree and record the
PASSED evidence a fresh operational payload requires; never touches the host.

The report (combined runner output) is kept beside the evidence and bound by
its SHA-256. Source tests are not native, deployment or useful-job acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from prepare_operational_release_428 import SOURCE_TEST_SCHEMA, require_committed_tree  # noqa: E402

RUNNER = 'scripts/run_source_tests_428.py'


def summarize(report):
    """The final pytest summary line; anything but a clean pass is refused."""
    lines = [line for line in report.splitlines()
             if re.search(r'\b\d+ (passed|failed|errors?)\b', line) and re.search(r' in [0-9.]+s\b', line)]
    if not lines:
        raise ValueError('The source-test report has no pytest summary')
    last = lines[-1]
    counts = {kind: int(number) for number, kind in re.findall(r'(\d+) (passed|failed|errors?|xpassed|xfailed)', last)}
    passed = counts.get('passed', 0)
    if passed < 1 or any(counts.get(kind, 0) for kind in ('failed', 'error', 'errors', 'xpassed')):
        raise ValueError('The source-test report is not a clean PASSED run')
    return passed


def record(destination, modules, *, timeout_seconds=3600, lock_timeout_seconds=5400, runner=subprocess.run):
    destination = Path(destination)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Use a fresh evidence directory under an existing directory')
    modules = sorted(set(modules))
    if not modules or any(not re.fullmatch(r'pipeline_tests/test_[a-z0-9_]+\.py', item)
                          or not (ROOT / item).is_file() for item in modules):
        raise ValueError('Name existing pipeline_tests/test_*.py modules')
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                            check=True, timeout=30).stdout.strip()
    require_committed_tree(ROOT, commit, paths=('src', 'scripts', 'pipeline_tests'))
    completed = runner([sys.executable, '-I', str(ROOT / RUNNER), '--timeout-seconds', str(timeout_seconds),
                        '--lock-timeout-seconds', str(lock_timeout_seconds), '--', *modules, '-q', '--tb=short'],
                       cwd=str(ROOT), capture_output=True, timeout=timeout_seconds + lock_timeout_seconds + 120)
    report = completed.stdout + completed.stderr
    destination.mkdir()
    with (destination / 'source-tests.log').open('xb') as stream:
        stream.write(report)
    if completed.returncode != 0:
        raise ValueError('Serialized source tests did not pass; the report is preserved')
    passed = summarize(report.decode('utf-8', 'replace'))
    require_committed_tree(ROOT, commit, paths=('src', 'scripts', 'pipeline_tests'))
    evidence = dict(schema=SOURCE_TEST_SCHEMA, source_commit=commit, runner=RUNNER, status='PASSED',
                    passed=passed, failed=0, modules=modules,
                    source_test_report_sha256=hashlib.sha256(report).hexdigest(), host_acceptance_executed=False)
    with (destination / 'source-test-evidence.json').open('xb') as stream:
        stream.write((json.dumps(evidence, indent=2) + '\n').encode('utf-8'))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=3600)
    parser.add_argument('--lock-timeout-seconds', type=int, default=5400)
    parser.add_argument('modules', nargs='+')
    args = parser.parse_args()
    print(json.dumps(record(args.destination, args.modules, timeout_seconds=args.timeout_seconds,
                            lock_timeout_seconds=args.lock_timeout_seconds), indent=2))


if __name__ == '__main__':
    main()
