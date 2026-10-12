"""Download locked runtime/MCP wheels without installing or executing payloads.

Uses uv's frozen, offline export for dependency selection and the existing
lockfile's URLs, sizes and hashes for every download. No source builds, cache
relocation, dependency updates or protected-state writes are performed.
Build-backend dependencies and the application wheel remain separate work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import tomllib
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

MAX_FILE = 256 * 1024 ** 2
MAX_TOTAL = 1024 ** 3


def select_wheels(lock, requirements, tags, environment):
    """Select exactly one compatible wheel per applicable frozen requirement."""
    ranks = {tag: rank for rank, tag in enumerate(tags)}
    rows, names = [], set()
    for line in requirements.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate(environment):
            continue
        specs = list(requirement.specifier)
        if (requirement.url or requirement.extras or len(specs) != 1
                or specs[0].operator != '==' or '*' in specs[0].version):
            raise ValueError('Export requires exact locked registry versions')
        name, version = canonicalize_name(requirement.name), specs[0].version
        if name in names:
            raise ValueError('Export contains duplicate applicable packages')
        names.add(name)
        packages = [p for p in lock['package'] if canonicalize_name(p['name']) == name
                    and p['version'] == version]
        if len(packages) != 1 or packages[0]['source'] != {'registry': 'https://pypi.org/simple'}:
            raise ValueError('Requirement is not uniquely pinned to the reviewed registry')
        choices = []
        for wheel in packages[0].get('wheels', []):
            url = urlsplit(wheel['url'])
            filename = url.path.rsplit('/', 1)[-1]
            if (url.scheme != 'https' or url.netloc != 'files.pythonhosted.org'
                    or url.query or url.fragment or not re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl', filename)):
                raise ValueError('Wheel URL is outside the pinned package host')
            wheel_name, wheel_version, _, wheel_tags = parse_wheel_filename(filename)
            if wheel_name != name or str(wheel_version) != version:
                raise ValueError('Wheel filename differs from locked package identity')
            if (not re.fullmatch('sha256:[a-f0-9]{64}', wheel.get('hash', ''))
                    or type(wheel.get('size')) is not int or not 0 < wheel['size'] <= MAX_FILE):
                raise ValueError('Wheel requires bounded size and SHA256')
            matched = wheel_tags & ranks.keys()
            if matched:
                choices.append((min(ranks[tag] for tag in matched), filename, wheel))
        if not choices:
            raise ValueError('No locked wheel supports the selected Python/platform')
        _, filename, wheel = min(choices, key=lambda item: (item[0], item[1]))
        rows.append(dict(name=name, version=version, filename=filename, url=wheel['url'],
                         sha256=wheel['hash'][7:], size=wheel['size']))
    if (not 1 <= len(rows) <= 256 or len({row['filename'].casefold() for row in rows}) != len(rows)
            or sum(row['size'] for row in rows) > MAX_TOTAL):
        raise ValueError('Wheel set exceeds bounded package/size limits')
    return sorted(rows, key=lambda row: row['name'])


def copy_verified(stream, destination, row, *, deadline=None):
    """Keep partial bytes for diagnosis, but never return success for bad bytes."""
    digest, length = hashlib.sha256(), 0
    with Path(destination).open('xb') as output:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('Wheel preparation exceeded its deadline')
            block = stream.read(min(1024 ** 2, row['size'] - length + 1))
            if not block:
                break
            length += len(block)
            if length > row['size']:
                raise ValueError('Downloaded wheel exceeds its locked size')
            output.write(block)
            digest.update(block)
    if length != row['size'] or digest.hexdigest() != row['sha256']:
        raise ValueError('Downloaded wheel does not match its locked size/hash')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Pinned wheel downloads cannot redirect')


def prepare(repository, destination, uv):
    repository, destination, uv = map(lambda p: Path(p).absolute(), (repository, destination, uv))
    if sys.version_info[:2] != (3, 12) or sys.platform != 'win32':
        raise ValueError('Prepare the host wheelhouse using the repository Windows Python 3.12')
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Wheelhouse requires a fresh destination under an existing directory')
    for path in (destination.parent, *destination.parent.parents):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Wheelhouse must not traverse redirected paths')
    if any('gdrive' in part.casefold() or 'google drive' in part.casefold() for part in destination.parts):
        raise ValueError('Wheelhouse must remain outside Google Drive')
    lock_bytes = (repository / 'uv.lock').read_bytes()
    project_bytes = (repository / 'pyproject.toml').read_bytes()
    if len(lock_bytes) > 16 * 1024 ** 2 or len(project_bytes) > 1024 ** 2:
        raise ValueError('Dependency inputs exceed bounds')
    uv_hash = hashlib.sha256(uv.read_bytes()).hexdigest()
    env = {key: value for key, value in os.environ.items() if not key.startswith(('UV_', 'PIP_'))}
    export = subprocess.run([str(uv), '--no-config', '--offline', 'export', '--frozen',
        '--extra', 'mcp', '--no-dev', '--no-default-groups', '--no-emit-project',
        '--no-annotate', '--no-header', '--no-hashes', '--no-python-downloads',
        '--project', str(repository), '--python', sys.executable],
        capture_output=True, check=True, timeout=60, env=env).stdout
    if len(export) > 1024 ** 2 or (repository / 'uv.lock').read_bytes() != lock_bytes or (
            repository / 'pyproject.toml').read_bytes() != project_bytes:
        raise ValueError('Frozen export changed dependency inputs or exceeded bounds')
    rows = select_wheels(tomllib.loads(lock_bytes.decode('utf-8')), export.decode('utf-8'),
                         list(sys_tags()), default_environment())
    manifest = dict(schema='cochem-r6-runtime-wheelhouse/1',
        lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
        pyproject_sha256=hashlib.sha256(project_bytes).hexdigest(), uv_sha256=uv_hash,
        export_sha256=hashlib.sha256(export).hexdigest(),
        python_version=sys.version.split()[0], platform=sys.platform, files=rows,
        total_bytes=sum(row['size'] for row in rows), packages_installed=0,
        source_builds=0, application_wheel_included=False,
        build_backend_complete=False, install_ready=False, deployment_accepted=False)
    destination.mkdir()
    with (destination / 'requirements-export.txt').open('xb') as output:
        output.write(export)
    with (destination / 'wheelhouse-plan.json').open('x', encoding='utf-8') as output:
        json.dump(manifest, output, indent=2)
    opener, deadline = build_opener(NoRedirect()), time.monotonic() + 600
    try:
        for row in rows:
            if time.monotonic() >= deadline:
                raise TimeoutError('Wheel preparation exceeded its deadline')
            with opener.open(row['url'], timeout=30) as response:
                copy_verified(response, destination / row['filename'], row, deadline=deadline)
        with (destination / 'wheelhouse-verified.json').open('x', encoding='utf-8') as output:
            json.dump(dict(manifest, status='LOCKED_RUNTIME_WHEELS_VERIFIED'), output, indent=2)
    except Exception as exc:
        with (destination / 'wheelhouse-held.json').open('x', encoding='utf-8') as output:
            json.dump(dict(schema=manifest['schema'], status='HELD_PRESERVE_PARTIAL',
                error_type=type(exc).__name__, install_ready=False), output, indent=2)
        raise
    return dict(status='LOCKED_RUNTIME_WHEELS_VERIFIED', destination=str(destination),
                files=len(rows), total_bytes=manifest['total_bytes'], install_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--uv', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.repository, args.destination, args.uv), indent=2))
    except Exception as exc:
        print(json.dumps(dict(status='WHEELHOUSE_PREPARATION_HELD', error_type=type(exc).__name__,
                              install_ready=False)))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
