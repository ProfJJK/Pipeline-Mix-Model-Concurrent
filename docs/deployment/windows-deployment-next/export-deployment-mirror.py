"""Export the curated deployment workspace into the pipeline repo for publication (the repo is PUBLIC).

Usage: <repo .venv python> -I -B export-deployment-mirror.py [--check]
--check: list what would be exported and run the secret scan only; copy nothing.
Without --check the destination folder is REPLACED (removed and rewritten), so commit or stash other edits there first.
Selection: top-level *.ps1/*.py/*.md/*.txt, the named JSON/log files below, the runner's pinned files, and the
r5-army-specs\\ and gemini-build-specs\\ folders. Add new sitting logs to TOP_EXTRA. Fixture/evidence/tmp folders,
XML outputs and large inventories are deliberately excluded.
Destination: <repo>\\docs\\deployment\\windows-deployment-next\\ (flat files + r5-army-specs\\ + gemini-build-specs\\),
plus EXPORT-MANIFEST.json (relative path, bytes, sha256). Refuses (exit 2) if the scan finds a credential-like value,
an e-mail address or a private key.
"""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

W = Path(r'C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next')
REPO = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent')
DEST = REPO / 'docs' / 'deployment' / 'windows-deployment-next'
TOP_EXT = {'.ps1', '.py', '.md', '.txt'}
TOP_JSON = {'R5_CHANGE_SPEC_20261011.json', 'GEMINI_BUILD_MANIFEST_20261010.json', 'stopped-runtime-r5-source-manifest.json',
            'stopped-runtime-r5-freeze-receipt.json', 'stopped-runtime-r4-source-manifest.json',
            'stopped-runtime-r3-source-manifest.json', 'execution-runtime-pins.json', 'binding-plan-r6a.json'}
TOP_EXTRA = {'r5-sitting-20261011-172252.log', 'r5-sitting-20261011-202738.log', 'launch-series-20261010-195717.log',
             'pytest.ini'}
SUBDIRS = ['r5-army-specs', 'gemini-build-specs']
MAX_BYTES = 2 * 1024 * 1024
PATTERNS = {
    'email': re.compile(rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
    'private_key': re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'google_oauth': re.compile(rb'ya29\.[A-Za-z0-9_\-]{20,}|1//[A-Za-z0-9_\-]{30,}'),
    'google_api_key': re.compile(rb'AIza[0-9A-Za-z_\-]{30,}'),
    'openai_key': re.compile(rb'\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}'),
    'anthropic_key': re.compile(rb'sk-ant-[A-Za-z0-9_\-]{20,}'),
    'github_token': re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}'),
    'bearer': re.compile(rb'Bearer\s+[A-Za-z0-9._\-]{20,}'),
    'json_secret': re.compile(rb'"(?:access_token|refresh_token|id_token|client_secret|api_key|password|token)"\s*:\s*"[^"\s]{12,}"', re.I),
}
EMAIL_OK = {b'noreply@anthropic.com'}
# RFC 2606 / 6761 reserved domains only appear in test fixtures.
EMAIL_OK_DOMAINS = (b'.invalid', b'@example.com', b'@example.org')
# Deliberate fake secrets inside test files (asserted to be redacted by the code under test).
FIXTURE_MARKERS = (b'SECRET', b'fixture', b'REDACTED', b'abcdef123456')


def allowed(rel, kind, hit):
    if kind == 'email':
        low = hit.lower()
        return hit in EMAIL_OK or low.endswith(EMAIL_OK_DOMAINS)
    return rel.rsplit('/', 1)[-1].startswith('test_') and any(m in hit for m in FIXTURE_MARKERS)


def pin_names():
    text = (W / 'refresh-r5-sitting-pins.py').read_text(encoding='utf-8')
    match = re.search(r'PIN_NAMES\s*=\s*\(?\[?(.*?)[\])]\s*\n', text, re.S)
    return set(re.findall(r"'([^']+)'", match.group(1))) if match else set()


def selected():
    files = []
    for path in sorted(W.iterdir()):
        if path.is_file() and (path.suffix in TOP_EXT or path.name in TOP_JSON or path.name in TOP_EXTRA):
            files.append(path)
    for name in sorted(pin_names()):
        path = W / name
        if path.is_file() and path not in files:
            files.append(path)
    for sub in SUBDIRS:
        for path in sorted((W / sub).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                files.append(path)
    return files


def main() -> int:
    check = '--check' in sys.argv[1:]
    files = selected()
    problems, manifest = [], []
    for path in files:
        data = path.read_bytes()
        rel = path.relative_to(W).as_posix()
        if len(data) > MAX_BYTES:
            problems.append(f'{rel}: larger than {MAX_BYTES} bytes')
        for kind, pattern in PATTERNS.items():
            for hit in pattern.findall(data):
                if allowed(rel, kind, hit):
                    continue
                problems.append(f'{rel}: {kind}: {hit[:60]!r}')
        manifest.append({'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    total = sum(item['bytes'] for item in manifest)
    print(f'{len(files)} files, {total/1024/1024:.2f} MiB selected')
    if problems:
        print('SCAN FINDINGS (export refused):')
        for line in problems[:200]:
            print('  ' + line)
        return 2
    if check:
        print('scan clean (check mode; nothing copied)')
        return 0
    if DEST.exists():
        shutil.rmtree(DEST)
    for path, item in zip(files, manifest):
        target = DEST / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    (DEST / 'EXPORT-MANIFEST.json').write_text(json.dumps({'source': str(W), 'files': manifest}, indent=1) + '\n', encoding='utf-8')
    print(f'exported to {DEST}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
