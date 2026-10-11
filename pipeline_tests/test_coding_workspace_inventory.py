"""Physical worker-workspace inventory on the ordinary user's temp storage.

These checks need no SYSTEM, Git or Docker: read_workspace observes real files
under tmp_path. On Windows, os.DirEntry.stat() reports st_nlink as 0, so the
inventory must take the link count from os.lstat while still refusing real
hard links, symbolic links and junctions.
"""
from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest

from cochem_pipeline import coding
from cochem_pipeline.coding import CodingProject, materialize, observed_changes, read_workspace, safe_path, validate_project_files
from pipeline_tests.windows_test_context import create_optional_symlink


# At least 30 lines, so a one-line edit stays inside the 80% rewrite guard.
FILES = {
    'src/answer.py': b''.join(b'# Existing documentation line %d\r\n' % number for number in range(1, 31)) + b'ANSWER = 41\r\n',
    'tests/test_existing.py': b'from src.answer import ANSWER\r\n\r\n\r\ndef test_answer():\r\n    assert ANSWER == 41\r\n',
    'README.md': b'# Synthetic inventory fixture\n\nLF lines stay LF.\n',
}


def _workspace(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    materialize(root, FILES, {'src/answer.py': '100755'})
    return root


def test_read_workspace_accepts_ordinary_materialized_files_byte_exact(tmp_path):
    root = _workspace(tmp_path)
    after = read_workspace(root)
    validate_project_files(after)
    assert after == FILES
    assert after['src/answer.py'].endswith(b'ANSWER = 41\r\n') and b'\r\n' not in after['README.md']


@pytest.mark.skipif(os.name != 'nt', reason='DirEntry link counts are zero only on Windows')
def test_windows_direntry_link_count_is_zero_but_inventory_uses_lstat(tmp_path):
    root = _workspace(tmp_path)
    with os.scandir(root / 'src') as listing:
        entries = [entry for entry in listing if entry.name == 'answer.py']
    assert len(entries) == 1
    # The documented precondition: this test exercises the Windows behaviour.
    assert entries[0].stat(follow_symlinks=False).st_nlink == 0
    assert os.lstat(entries[0].path).st_nlink == 1
    assert read_workspace(root) == FILES


def test_controller_applied_edit_round_trips_through_read_workspace(tmp_path):
    root = _workspace(tmp_path)
    before = read_workspace(root)
    assert before == FILES
    edited = FILES['src/answer.py'].replace(b'ANSWER = 41\r\n', b'ANSWER = 42\r\n')
    proposal = {**before, 'src/answer.py': edited}
    # Mirrors the controller write after native tree closure (coding.py).
    for name, data in proposal.items():
        if before.get(name) != data:
            target = root / safe_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    after = read_workspace(root)
    assert after == proposal
    project = CodingProject.from_dict('p', {'repository': str(tmp_path), 'branch': 'delivery', 'allowed_paths': ['src']})
    changes = observed_changes(FILES, after, FILES, project)
    assert [change['path'] for change in changes] == ['src/answer.py']
    assert changes[0]['changed_lines'] == 2
    assert '-ANSWER = 41\r\n' in changes[0]['patch'] and '+ANSWER = 42\r\n' in changes[0]['patch']


@pytest.mark.parametrize('internal', [False, True])
def test_read_workspace_refuses_a_real_hardlink(tmp_path, internal):
    root = _workspace(tmp_path)
    assert read_workspace(root) == FILES
    external = tmp_path / 'synthetic-external-input.py'
    external.write_bytes(b'Not a real secret; physical external inode fixture\n')
    target = root / 'src' / 'answer.py' if internal else external
    (root / 'src' / 'linked.py').hardlink_to(target)
    assert os.lstat(root / 'src' / 'linked.py').st_nlink == 2
    with pytest.raises(ValueError, match='non-regular or hard-linked file'):
        read_workspace(root)
    assert external.read_bytes() == b'Not a real secret; physical external inode fixture\n'
    assert (root / 'src' / 'answer.py').read_bytes() == FILES['src/answer.py']


def test_read_workspace_refuses_a_symlink(tmp_path):
    root = _workspace(tmp_path)
    assert read_workspace(root) == FILES
    outside = tmp_path / 'outside.py'
    outside.write_bytes(b'OUTSIDE = True\n')
    create_optional_symlink(root / 'src' / 'link.py', outside)
    with pytest.raises(ValueError, match='symbolic link or reparse point'):
        read_workspace(root)
    assert outside.read_bytes() == b'OUTSIDE = True\n'


@pytest.mark.skipif(os.name != 'nt', reason='Junctions are a Windows reparse point')
def test_read_workspace_refuses_a_junction(tmp_path):
    import _winapi
    root = _workspace(tmp_path)
    assert read_workspace(root) == FILES
    outside = tmp_path / 'outside-directory'
    outside.mkdir()
    (outside / 'keep.py').write_bytes(b'KEEP = True\n')
    junction = root / 'src' / 'redirected'
    _winapi.CreateJunction(str(outside), str(junction))
    try:
        assert os.lstat(junction).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        with pytest.raises(ValueError, match='symbolic link or reparse point'):
            read_workspace(root)
    finally:
        os.rmdir(junction)
    assert (outside / 'keep.py').read_bytes() == b'KEEP = True\n'


@pytest.mark.parametrize('observed,message', [
    ('symlink', 'symbolic link or reparse point'),
    ('directory', 'changed while being inventoried'),
])
def test_lstat_metadata_is_checked_independently_of_the_listing(tmp_path, monkeypatch, observed, message):
    root = _workspace(tmp_path)
    answer = os.path.normcase(str(root / 'src' / 'answer.py'))
    modes = {'symlink': stat.S_IFLNK | 0o777, 'directory': stat.S_IFDIR | 0o777}
    def lstat(path):
        result = os.lstat(path)
        if os.path.normcase(str(path)) != answer:
            return result
        return os.stat_result((modes[observed],) + tuple(result)[1:])
    monkeypatch.setattr(coding, 'os', SimpleNamespace(scandir=os.scandir, lstat=lstat))
    with pytest.raises(ValueError, match=message):
        read_workspace(root)
