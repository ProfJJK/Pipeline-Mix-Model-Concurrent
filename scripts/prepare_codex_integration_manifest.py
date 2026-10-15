"""Export the exact reviewed Codex integration templates; never install them."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

FILES = ('SKILL.md', 'agents/openai.yaml', 'AGENTS.md', 'mcp.template.toml')
PREFIX = 'docs/4.2.8/integrations/codex/'


def prepare(repository: Path, commit: str, destination: Path):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('An exact source commit is required')
    destination = destination.absolute()
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Use a fresh destination under an existing ordinary directory')
    for path in (destination.parent, *destination.parent.parents):
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Integration export cannot traverse a redirected directory')
    if any('gdrive' in part.casefold() or 'google drive' in part.casefold() for part in destination.parts):
        raise ValueError('Integration export must be outside Google Drive')
    captured = {}
    for name in FILES:
        result = subprocess.run(['git', '-C', str(repository), 'show', commit + ':' + PREFIX + name],
                                check=True, capture_output=True, timeout=30)
        if not result.stdout or len(result.stdout) > 128 * 1024:
            raise ValueError('Integration input size is outside the reviewed bound')
        captured[name] = result.stdout
    destination.mkdir()
    entries = []
    for name, data in captured.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
        entries.append(dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
    result = dict(schema='cochem-codex-integration-export/1', source_commit=commit,
                  files=entries, installed=False, personal_config_read=False,
                  provider_commands_executed=0, other_integrations_changed=False)
    with (destination / 'integration-manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.repository, args.commit, args.destination)))


if __name__ == '__main__':
    main()
