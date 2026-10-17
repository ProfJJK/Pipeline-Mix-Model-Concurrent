"""Export the exact reviewed Codex integration templates, or build the scoped
update manifest that binds them to the owner's current Codex files and a runtime
root; never installs them (only the owner launch applies, with a live re-check)."""
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


def prepare_update(export: Path, destination: Path, *, user_home: Path, runtime_root: str, client_config: str):
    """Hashes the owner's current Codex files and validates the exact patch."""
    import sys
    source = Path(__file__).resolve().parents[1] / 'src'
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    import cochem_pipeline
    from cochem_pipeline.codex_integration_428 import prepare as prepare_codex_update
    if Path(cochem_pipeline.__file__).resolve().parent != (source / 'cochem_pipeline').resolve():
        raise ValueError("Codex update must be prepared by this checkout's runtime source")
    destination = destination.absolute()
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Use a fresh destination file under an existing ordinary directory')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from prepare_operational_release_428 import require_committed_tree
    inventory = json.loads((Path(export) / 'integration-manifest.json').read_bytes())
    # The transformation is validated by working-tree code: it must be the
    # exported (packaged) commit's.
    require_committed_tree(Path(__file__).resolve().parents[1], inventory.get('source_commit'))
    manifest = prepare_codex_update(export, user_home, runtime_root, client_config)
    data = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    with destination.open('xb') as stream:
        stream.write(data)
    return dict(schema='cochem-codex-integration-update-prepared/1', path=str(destination),
                sha256=hashlib.sha256(data).hexdigest(), source_commit=manifest['source_commit'],
                runtime_root=manifest['runtime_root'], files_changed=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--commit')
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--update-from-export', type=Path)
    parser.add_argument('--user-home', type=Path)
    parser.add_argument('--runtime-root')
    parser.add_argument('--client-config')
    args = parser.parse_args()
    if args.update_from_export is not None:
        if None in (args.user_home, args.runtime_root, args.client_config):
            parser.error('--update-from-export needs --user-home, --runtime-root and --client-config')
        print(json.dumps(prepare_update(args.update_from_export, args.destination, user_home=args.user_home,
                                        runtime_root=args.runtime_root, client_config=args.client_config)))
        return
    if args.repository is None or args.commit is None:
        parser.error('--repository and --commit are required for an export')
    print(json.dumps(prepare(args.repository, args.commit, args.destination)))


if __name__ == '__main__':
    main()
