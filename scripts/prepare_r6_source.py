"""Freeze committed R6 source and knowledge into a new ordinary staging folder.

This prepares files only. It never installs, starts a process from the payload,
changes protected state, or claims native deployment acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile

MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 4096, 16 * 1024**2, 128 * 1024**2
ROOT_FILES = {'README.md', 'pyproject.toml', 'uv.lock'}


def validate_name(name):
    parts = PurePosixPath(name).parts
    if (not parts or name.startswith('/') or '\\' in name
            or re.search(r'[\x00-\x1f<>:"|?*]', name)
            or any(part in ('', '.', '..') or part.endswith(('.', ' '))
                   or re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part) for part in name.split('/'))
            or (parts[0] not in ('src', 'knowledge') and name not in ROOT_FILES)):
        raise ValueError('Source archive contains an unsafe or unexpected path')


def inspect_archive(raw):
    if not 512 <= len(raw) <= MAX_TOTAL_BYTES:
        raise ValueError('Source archive exceeds its byte bound')
    files, folded, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        for entry in archive:
            name = entry.name.rstrip('/')
            validate_name(name)
            if entry.isdir():
                continue
            if not entry.isfile() or name.casefold() in folded:
                raise ValueError('Source archive contains a link, duplicate or special file')
            if not 0 <= entry.size <= MAX_FILE_BYTES or len(files) >= MAX_FILES:
                raise ValueError('Source archive file exceeds its bound')
            total += entry.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError('Source files exceed their total byte bound')
            stream = archive.extractfile(entry)
            data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) != entry.size:
                raise ValueError('Source archive member is incomplete')
            files[name] = data
            folded.add(name.casefold())
    required = ROOT_FILES | {'src/cochem_pipeline/specification/routing_catalog_v3.json',
                            'knowledge/v4.1.2_manifest.json'}
    if not required <= files.keys():
        raise ValueError('Source archive omits required runtime or knowledge assets')
    return files


def freeze(files, destination, commit):
    destination = Path(destination).absolute()
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Freeze requires a full committed Git revision')
    for path in (destination, *destination.parents):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Staging destination must not traverse a redirected path')
    if any('gdrive' in part.casefold() or 'google drive' in part.casefold() for part in destination.parts):
        raise ValueError('Pipeline staging must remain outside Google Drive')
    if not 1 <= len(files) <= MAX_FILES or len({name.casefold() for name in files}) != len(files):
        raise ValueError('Source inventory has invalid count or duplicate names')
    for name, data in files.items():
        validate_name(name)
        if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
            raise ValueError('Source inventory contains an invalid file')
    if sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        raise ValueError('Source inventory exceeds its total byte bound')
    # Build/validate metadata before creating any destination. The caller's files
    # must come from inspect_archive; all writes below stay inside the new root.
    rows = [dict(relative=name, length=len(data), sha256=hashlib.sha256(data).hexdigest())
            for name, data in sorted(files.items())]
    manifest = dict(schema='cochem-r6-source-preparation/1', commit=commit,
                    files=rows, payload_bytes=sum(row['length'] for row in rows),
                    install_ready=False, deployment_accepted=False)
    payload = (json.dumps(manifest, indent=2) + '\n').encode()
    destination.mkdir(parents=False, exist_ok=False)
    for row in rows:
        target = destination / row['relative']
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(files[row['relative']])
        if hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Frozen source changed after writing; preserve the partial root')
    with (destination / 'source-preparation.json').open('xb') as stream:
        stream.write(payload)
    return dict(schema='cochem-r6-source-preparation-result/1', commit=commit,
                destination=str(destination), files=len(rows), payload_bytes=manifest['payload_bytes'],
                manifest_sha256=hashlib.sha256(payload).hexdigest(), install_ready=False,
                deployment_accepted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.commit):
        parser.error('--commit must be a full 40-character Git revision')
    archive = subprocess.run(['git', '-C', str(args.repository), 'archive', '--format=tar',
                              args.commit, '--', *sorted(ROOT_FILES), 'src', 'knowledge'],
                             check=True, capture_output=True, timeout=60).stdout
    print(json.dumps(freeze(inspect_archive(archive), args.destination, args.commit), indent=2))


if __name__ == '__main__':
    main()
