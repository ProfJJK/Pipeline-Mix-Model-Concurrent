"""Assemble verified offline R6 installation inputs in a fresh user-owned folder.

No installation or acceptance is performed. This manifest is for the stopped
installer; it is deliberately not a license to activate an untested candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from cochem_pipeline.config import load_config
from cochem_pipeline.r6_candidate import from_commissioned_bytes


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_pinned(path, pin, size):
    path = Path(path)
    if type(size) is not int or not 0 <= size <= 268435456 or not re.fullmatch('[a-f0-9]{64}', pin):
        raise ValueError('Invalid bundle payload bounds')
    for current in (path, *path.parents):
        info = current.lstat()
        if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Bundle payload traverses a redirected path')
    if path.stat().st_nlink != 1 or path.stat().st_size != size:
        raise ValueError('Bundle payload identity or length changed')
    data = path.read_bytes()
    if digest(data) != pin:
        raise ValueError('Bundle payload digest changed')
    return data


def relative(name):
    if (not isinstance(name, str) or not name or name.startswith('/') or '\\' in name
            or re.search(r'[\x00-\x1f<>:"|?*]', name)
            or any(p in ('', '.', '..') or p.endswith(('.', ' '))
                   or re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
                   for p in name.split('/'))):
        raise ValueError('Unsafe bundle relative path')
    return name


def prepare(freeze, wheelhouse, application, commissioned, destination):
    freeze, wheelhouse, application, commissioned, destination = map(Path,
        (freeze, wheelhouse, application, commissioned, destination))
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Bundle needs a fresh directory')
    for current in (destination.parent, *destination.parent.parents):
        info = current.lstat()
        if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Bundle destination traverses a redirected path')
    if any('gdrive' in p.casefold() or 'google drive' in p.casefold() for p in destination.parts):
        raise ValueError('Bundle must be outside Google Drive')
    source = json.loads((freeze / 'source-preparation.json').read_text())
    wheels = json.loads((wheelhouse / 'wheelhouse-verified.json').read_text())
    app = json.loads(application.read_text())
    if (source['schema'] != 'cochem-r6-source-preparation/1'
            or wheels['status'] != 'LOCKED_RUNTIME_WHEELS_VERIFIED'
            or app['status'] != 'APPLICATION_WHEEL_VERIFIED'
            or app['source_commit'] != source['commit']
            or app['source_manifest_sha256'] != digest((freeze / 'source-preparation.json').read_bytes())
            or wheels['lock_sha256'] != digest((freeze / 'uv.lock').read_bytes())
            or wheels['pyproject_sha256'] != digest((freeze / 'pyproject.toml').read_bytes())):
        raise ValueError('Offline inputs do not bind the same source/dependency set')
    # Recheck application bytes against source, not just the preparation claim.
    from build_r6_application import verify_wheel
    actual_app = verify_wheel(Path(app['wheel']), freeze)
    if any(actual_app[k] != app[k] for k in ('sha256', 'size', 'files')):
        raise ValueError('Application verification changed')
    candidate, plan = from_commissioned_bytes(commissioned.read_bytes())
    files, folded = [], set()
    def add(name, path, pin, size):
        relative(name)
        if name.casefold() in folded:
            raise ValueError('Duplicate bundle payload')
        folded.add(name.casefold())
        read_pinned(path, pin, size)
        files.append(dict(relative=name, source=str(Path(path).absolute()), sha256=pin, length=size))
    for row in source['files']:
        relative(row['relative'])
        add('source/' + row['relative'], freeze / row['relative'], row['sha256'], row['length'])
    requirements = []
    for row in wheels['files']:
        relative(row['filename'])
        if '/' in row['filename'] or not re.fullmatch('[a-z0-9][a-z0-9.-]*', row['name']) or not re.fullmatch('[A-Za-z0-9.+!-]+', row['version']):
            raise ValueError('Invalid locked wheel identity')
        add('wheels/' + row['filename'], wheelhouse / row['filename'], row['sha256'], row['size'])
        requirements.append(f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}")
    add('wheels/cochem-4.2.7-py3-none-any.whl', app['wheel'], app['sha256'], app['size'])
    requirements.append('cochem==4.2.7 --hash=sha256:' + app['sha256'])
    destination.mkdir()
    def write(name, value):
        data = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode() if not isinstance(value, bytes) else value
        with (destination / name).open('xb') as out:
            out.write(data)
        return data
    try:
        raw = write('pipeline.json', candidate)
        # Production parser, without opening a database or executing a provider.
        parsed = load_config(destination / 'pipeline.json')
        if parsed.max_execution_slots != 4:
            raise ValueError('Parsed candidate changed execution capacity')
        add('pipeline.json', destination / 'pipeline.json', digest(raw), len(raw))
        raw = write('runtime-requirements.txt', ('\n'.join(requirements) + '\n').encode())
        add('wheels/runtime-requirements.txt', destination / 'runtime-requirements.txt', digest(raw), len(raw))
        write('native-acceptance-plan.json', plan)
        manifest = dict(schema='cochem-r6-install-bundle/1', host='AETHERDESK', revision='windows-20261012-r6-v1',
            source_commit=source['commit'], files=files, activation_ready=False)
        encoded = write('install-manifest.json', manifest)
        receipt = dict(schema='cochem-r6-bundle-preparation/1', status='STOPPED_INSTALL_INPUTS_VERIFIED',
            manifest_sha256=digest(encoded), source_commit=source['commit'], payload_files=len(files),
            payload_bytes=sum(r['length'] for r in files), candidate_sha256=digest((destination / 'pipeline.json').read_bytes()),
            native_acceptance_plan_sha256=plan['plan_sha256'], installation_inputs_ready=True,
            administrator_launch_ready=False, native_acceptance_completed=False, activation_ready=False)
        write('bundle-prepared.json', receipt)
        return receipt
    except Exception as exc:
        write('bundle-held.json', dict(status='HELD_PRESERVE_PARTIAL', error_type=type(exc).__name__, activation_ready=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('freeze', 'wheelhouse', 'application', 'commissioned', 'destination'):
        parser.add_argument('--' + name, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args())), indent=2))
