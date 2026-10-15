"""Pinned, Codex-only integration update; no provider, service or shell calls.

The owner launcher invokes apply only after the new runtime is verified. The
manifest contains hashes and public templates, never the personal configuration.
Existing files must still match preparation. Private backups stay in the user's
Codex directory. A changed file is held rather than overwritten on recovery.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib
import uuid


FILES = {'config': '.codex/config.toml', 'rules': '.codex/AGENTS.md',
         'skill': '.agents/skills/codex-pipeline/SKILL.md',
         'metadata': '.agents/skills/codex-pipeline/agents/openai.yaml'}
TEMPLATES = {'rules': 'AGENTS.md', 'skill': 'SKILL.md', 'metadata': 'agents/openai.yaml'}
RULE_HEADING = '# Codex: CoChem pipeline submissions'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    path = Path(path)
    if not path.is_absolute() or any(p.casefold() in {'gdrive', 'google drive'} for p in path.parts):
        raise ValueError('Codex integration requires an absolute local path outside Google Drive')
    for item in (path, *path.parents):
        info = item.lstat()
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Codex integration cannot traverse redirected paths')
    return path


def read(path):
    path = ordinary(path)
    with path.open('rb') as stream:
        data = stream.read(1024 * 1024 + 1)
    if not data or len(data) > 1024 * 1024:
        raise ValueError('Codex integration input exceeds its bound')
    return data


def patch_config(raw, runtime_root, client_config):
    """Replace exactly one existing server table; preserve every other byte."""
    text = raw.decode('utf-8-sig')
    before = tomllib.loads(text)
    old = before.get('mcp_servers', {}).get('cochem-pipeline')
    if not isinstance(old, dict) or set(old) - {'command', 'args', 'enabled', 'startup_timeout_sec', 'tool_timeout_sec'}:
        raise ValueError('Unexpected Codex pipeline server settings require scoped review')
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if re.fullmatch(
        r'\s*\[mcp_servers\.(?:cochem-pipeline|"cochem-pipeline"|\'cochem-pipeline\')\]\s*(?:#.*)?', line.rstrip('\r\n'))]
    if len(starts) != 1:
        raise ValueError('Expected exactly one Codex pipeline server table')
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith('[')), len(lines))
    command = str(Path(runtime_root) / '.venv' / 'Scripts' / 'python.exe')
    args = ['-I', '-B', '-m', 'cochem_pipeline', 'mcp', '--client-config', client_config]
    newline = '\r\n' if '\r\n' in text else '\n'
    replacement = ['[mcp_servers."cochem-pipeline"]', 'enabled = true',
                   'command = ' + json.dumps(command), 'args = ' + json.dumps(args)]
    for key in ('startup_timeout_sec', 'tool_timeout_sec'):
        if key in old:
            if type(old[key]) not in (int, float) or not 0 < old[key] <= 3600:
                raise ValueError('Unexpected Codex pipeline timeout')
            replacement.append(key + ' = ' + str(old[key]))
    rendered = ''.join(lines[:start]) + newline.join(replacement) + newline * 2 + ''.join(lines[end:])
    after = tomllib.loads(rendered)
    expected = deepcopy(before)
    expected['mcp_servers']['cochem-pipeline'] = dict(old, enabled=True, command=command, args=args)
    if after != expected:
        raise ValueError('Codex update changed unrelated settings')
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + rendered.encode('utf-8')


def patch_rules(raw, template):
    text = raw.decode('utf-8-sig')
    match = re.search(r'(?m)^' + re.escape(RULE_HEADING) + r'\s*$', text)
    if not match or re.search(r'(?m)^' + re.escape(RULE_HEADING) + r'\s*$', text[match.end():]):
        raise ValueError('Expected exactly one managed Codex pipeline rule')
    following = re.search(r'(?m)^# ', text[match.end():])
    end = match.end() + following.start() if following else len(text)
    replacement = template.decode('utf-8').strip() + '\n\n'
    return (text[:match.start()] + replacement + text[end:]).encode('utf-8')


def prepare(export, user_home, runtime_root, client_config):
    export, user_home = ordinary(export), ordinary(user_home)
    inventory = json.loads(read(export / 'integration-manifest.json'))
    if (inventory.get('schema') != 'cochem-codex-integration-export/1'
            or not re.fullmatch('[a-f0-9]{40}', str(inventory.get('source_commit', '')))):
        raise ValueError('Expected an exact source integration export')
    pins = {row['path']: row for row in inventory['files']}
    templates = {}
    for key, name in TEMPLATES.items():
        raw = read(export / name)
        if name not in pins or sha(raw) != pins[name]['sha256'] or len(raw) != pins[name]['size']:
            raise ValueError('Export template differs from its source pin')
        templates[key] = raw.decode('utf-8')
    expected = {key: sha(read(user_home / relative)) for key, relative in FILES.items()}
    # Validate exact transformations now, without staging personal config bytes.
    patch_config(read(user_home / FILES['config']), str(runtime_root), str(client_config))
    patch_rules(read(user_home / FILES['rules']), templates['rules'].encode())
    return dict(schema='cochem-codex-integration-update/1', source_commit=inventory['source_commit'],
                user_home=str(user_home), runtime_root=str(runtime_root), client_config=str(client_config),
                expected=expected, templates=templates, refresh_required=True,
                provider_commands_executed=0, other_integrations_changed=False)


def _capture_update(manifest):
    if (manifest.get('schema') != 'cochem-codex-integration-update/1'
            or set(manifest.get('expected', {})) != set(FILES)
            or set(manifest.get('templates', {})) != set(TEMPLATES)):
        raise ValueError('Invalid scoped Codex update')
    home = ordinary(manifest['user_home'])
    ordinary(Path(manifest['runtime_root']) / '.venv' / 'Scripts' / 'python.exe')
    ordinary(manifest['client_config'])
    paths = {key: home / relative for key, relative in FILES.items()}
    originals = {key: read(path) for key, path in paths.items()}
    if any(sha(raw) != manifest['expected'][key] for key, raw in originals.items()):
        raise ValueError('Codex settings changed since preparation; no files updated')
    updated = {key: text.encode('utf-8') for key, text in manifest['templates'].items()}
    updated['config'] = patch_config(originals['config'], manifest['runtime_root'], manifest['client_config'])
    updated['rules'] = patch_rules(originals['rules'], updated['rules'])
    return home, paths, originals, updated


def verify_plan(manifest):
    """Validate existing targets and transformations without writing any file."""
    _capture_update(manifest)
    return dict(status='CODEX_UPDATE_PLAN_VERIFIED', source_commit=manifest['source_commit'],
                refresh_required=True, files_changed=0, current_session_tools_loaded=False)


def apply(manifest, *, replace=os.replace):
    home, paths, originals, updated = _capture_update(manifest)
    backups = home / '.codex' / ('pipeline-integration-backup-' + uuid.uuid4().hex)
    backups.mkdir()
    for key, raw in originals.items():
        with (backups / (key + '.original')).open('xb') as stream:
            stream.write(raw)
    changed, restored, conflicts = [], [], []
    try:
        for key, path in paths.items():
            if read(path) != originals[key]:
                raise ValueError('Concurrent Codex settings edit; preserving it')
            temporary = path.with_name(path.name + '.cochem-' + uuid.uuid4().hex)
            with temporary.open('xb') as stream:
                stream.write(updated[key]); stream.flush(); os.fsync(stream.fileno())
            if read(path) != originals[key]:
                raise ValueError('Concurrent Codex settings edit before replacement')
            replace(temporary, path)
            changed.append(key)
        if any(read(paths[key]) != value for key, value in updated.items()):
            raise ValueError('Codex update verification changed')
    except BaseException:
        for key in reversed(changed):
            try:
                if read(paths[key]) != updated[key]:
                    conflicts.append(key)
                    continue
                temporary = paths[key].with_name(paths[key].name + '.restore-' + uuid.uuid4().hex)
                with temporary.open('xb') as stream:
                    stream.write(originals[key]); stream.flush(); os.fsync(stream.fileno())
                replace(temporary, paths[key]); restored.append(key)
            except (OSError, ValueError):
                # A concurrent deletion/redirect or an inaccessible backup must
                # not prevent recovery of other unchanged files or hide the
                # original failure. Leave this path and its backup for review.
                conflicts.append(key)
        (backups / 'held.json').write_text(json.dumps(dict(status='HELD_PRESERVE_EVIDENCE',
            changed=changed, restored=restored, concurrent_or_restore_conflicts=conflicts)), encoding='utf-8')
        raise
    result = dict(status='CODEX_INTEGRATION_UPDATED_REFRESH_REQUIRED', source_commit=manifest['source_commit'],
                  files={key: sha(value) for key, value in updated.items()}, backup_root=str(backups),
                  refresh_required=True, current_session_tools_loaded=False,
                  other_integrations_changed=False, provider_commands_executed=0)
    (backups / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    raw = read(args.manifest)
    if sha(raw) != args.manifest_sha256:
        raise ValueError('Codex update manifest differs from reviewed pin')
    manifest = json.loads(raw)
    print(json.dumps(apply(manifest) if args.apply else verify_plan(manifest)))


if __name__ == '__main__':
    main()
