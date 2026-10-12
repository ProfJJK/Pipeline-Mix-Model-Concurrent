"""Build one application wheel offline from an immutable committed source freeze.

Runs the reviewed setuptools backend in uv's isolated build environment. Never
installs the application or alters a protected runtime. Partial outputs remain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_wheel(path, source):
    """Every packaged source/asset must match; extra application files refuse."""
    source = Path(source)
    expected = {p.relative_to(source / 'src').as_posix(): p.read_bytes()
        for p in (source / 'src').rglob('*') if p.is_file() and '__pycache__' not in p.parts
        and p.suffix in {'.py', '.md', '.json', '.xml', '.typed'}}
    actual = {}
    with zipfile.ZipFile(path) as wheel:
        seen, total = set(), 0
        for entry in wheel.infolist():
            name = entry.filename
            parts = PurePosixPath(name).parts
            total += entry.file_size
            if (name.casefold() in seen or name.startswith('/') or '\\' in name
                    or any(p in ('', '.', '..') for p in name.split('/'))
                    or entry.file_size > 16 * 1024**2 or total > 128 * 1024**2):
                raise ValueError('Unsafe, duplicate or oversized application wheel entry')
            seen.add(name.casefold())
            if len(parts) > 1 and parts[0].endswith('.dist-info'):
                if parts[0] != 'cochem-4.2.7.dist-info':
                    raise ValueError('Unexpected wheel package identity')
                continue
            if not parts or not parts[0].startswith('cochem'):
                raise ValueError('Unexpected application wheel payload')
            actual[name] = wheel.read(entry)
    if not expected or actual != expected:
        raise ValueError('Application wheel does not exactly match frozen source/assets')
    return dict(files=len(actual), sha256=sha(Path(path).read_bytes()), size=Path(path).stat().st_size)


def build(freeze, backend, destination, uv, python):
    freeze, backend, destination, uv = map(Path, (freeze, backend, destination, uv))
    manifest = json.loads((freeze / 'source-preparation.json').read_text())
    if manifest['schema'] != 'cochem-r6-source-preparation/1' or destination.exists():
        raise ValueError('Build needs a source freeze and fresh destination')
    payload = {}
    for row in manifest['files']:
        name = row['relative']
        if name.startswith('/') or '\\' in name or '..' in PurePosixPath(name).parts:
            raise ValueError('Invalid frozen source member')
        data = (freeze / name).read_bytes()
        if sha(data) != row['sha256'] or len(data) != row['length']:
            raise ValueError('Frozen source bytes changed')
        payload[name] = data
    controls = json.loads((backend / 'backend-verified.json').read_text())
    if controls['schema'] != 'cochem-r6-build-backend-preparation/1':
        raise ValueError('Unknown backend preparation')
    for row in controls['files']:
        if Path(row['filename']).name != row['filename']:
            raise ValueError('Invalid backend filename')
        data = (backend / row['filename']).read_bytes()
        if sha(data) != row['sha256'] or len(data) != row['size']:
            raise ValueError('Backend wheel changed')
    constraints = backend / 'build-constraints.txt'
    if sha(constraints.read_bytes()) != controls['constraints_sha256']:
        raise ValueError('Backend constraints changed')
    destination.mkdir()
    source = destination / 'source'
    source.mkdir()
    for name, data in payload.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('UV_', 'PIP_', 'PYTHON'))
           and k != 'VIRTUAL_ENV'}
    env['SOURCE_DATE_EPOCH'] = '1791763200'
    command = [str(uv), '--no-config', '--no-cache', '--offline', 'build', str(source), '--wheel',
        '--no-index', '--find-links', str(backend), '--build-constraints', str(constraints),
        '--require-hashes', '--python', python, '--no-python-downloads', '--link-mode', 'copy',
        '--out-dir', str(destination / 'dist'), '--no-create-gitignore']
    try:
        with (destination / 'build.stdout.log').open('xb') as out, (destination / 'build.stderr.log').open('xb') as err:
            subprocess.run(command, check=True, timeout=180, env=env, stdout=out, stderr=err)
        wheels = list((destination / 'dist').iterdir())
        if len(wheels) != 1 or wheels[0].name != 'cochem-4.2.7-py3-none-any.whl':
            raise ValueError('Build did not produce exactly the reviewed wheel')
        result = dict(schema='cochem-r6-application-wheel/1', status='APPLICATION_WHEEL_VERIFIED',
            source_commit=manifest['commit'], source_manifest_sha256=sha((freeze / 'source-preparation.json').read_bytes()),
            backend_receipt_sha256=sha((backend / 'backend-verified.json').read_bytes()),
            uv_sha256=sha(uv.read_bytes()), wheel=str(wheels[0]), **verify_wheel(wheels[0], freeze),
            application_installed=False, deployment_accepted=False)
        (destination / 'application-wheel.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    except Exception as exc:
        (destination / 'build-held.json').write_text(json.dumps(dict(status='HELD_PRESERVE_PARTIAL',
            error_type=type(exc).__name__, deployment_accepted=False)), encoding='utf-8')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('freeze', 'backend', 'destination', 'uv', 'python'):
        parser.add_argument('--' + name, required=True)
    print(json.dumps(build(**vars(parser.parse_args())), indent=2))
