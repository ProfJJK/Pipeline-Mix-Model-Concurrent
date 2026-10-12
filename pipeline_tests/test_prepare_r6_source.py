"""Ordinary temporary archives only; no Git commands, installs or native jobs."""
import io
import json
import tarfile

import pytest

from scripts.prepare_r6_source import ROOT_FILES, inspect_archive, freeze


def archive(extra=(), *, link=False):
    output = io.BytesIO()
    names = [*sorted(ROOT_FILES), 'src/cochem_pipeline/specification/routing_catalog_v3.json',
             'knowledge/v4.1.2_manifest.json', *extra]
    with tarfile.open(fileobj=output, mode='w:') as bundle:
        for name in names:
            row = tarfile.TarInfo(name)
            row.size = 3
            if link and name in extra:
                row.type, row.linkname = tarfile.SYMTYPE, '../../outside'
            bundle.addfile(row, io.BytesIO(b'old'))
    return output.getvalue()


def test_frozen_commit_bytes_survive_worktree_changes_and_existing_destination_is_preserved(tmp_path):
    files = inspect_archive(archive())
    root = tmp_path / 'fresh'
    result = freeze(files, root, 'a' * 40)
    manifest = json.loads((root / 'source-preparation.json').read_text())
    assert result['files'] == len(files) and not result['install_ready']
    assert manifest['commit'] == 'a' * 40
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    with pytest.raises(FileExistsError):
        freeze({key: b'changed' for key in files}, root, 'b' * 40)
    assert all((root / name).read_bytes() == raw for name, raw in before.items())


@pytest.mark.parametrize('path', ['../escape', 'src/../../escape', '/absolute', 'src/CON.py',
                                  'src/thing.py:stream', 'src/space. /x', 'src\\escape', 'README.md'])
def test_archive_refuses_escaping_ambiguous_or_duplicate_paths(path):
    with pytest.raises(ValueError):
        inspect_archive(archive([path]))


def test_archive_refuses_symbolic_links():
    with pytest.raises(ValueError):
        inspect_archive(archive(['src/link'], link=True))


def test_incomplete_archive_and_noncommit_identifier_fail_before_staging(tmp_path):
    with pytest.raises(ValueError):
        inspect_archive(b'')
    with pytest.raises(ValueError):
        freeze(inspect_archive(archive()), tmp_path / 'fresh', 'HEAD')
    assert not (tmp_path / 'fresh').exists()
