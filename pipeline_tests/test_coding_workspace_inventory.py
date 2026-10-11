"""Physical worker-workspace inventory on the ordinary user's temp storage.

These checks need no SYSTEM, Git or Docker: read_workspace observes real files
under tmp_path. On Windows, os.DirEntry.stat() reports st_nlink as 0, so the
inventory must take the link count from os.lstat while still refusing real
hard links, symbolic links and junctions.
"""
from __future__ import annotations

import contextlib
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


_REPARSE = 'Worker created a symbolic link or reparse point'
_LINKED = 'Worker created a non-regular or hard-linked file'
_CHANGED = 'Worker workspace entry changed while being inventoried'
_OVERSIZE = 'Worker snapshot exceeds the bounded project size'


def _metadata(result, **changes):
    # A plain view of the fields read_workspace reads. A truncated os.stat_result
    # would turn the Windows-only st_file_attributes field into None.
    fields = {name: getattr(result, name, 0) for name in ('st_mode', 'st_nlink', 'st_size', 'st_file_attributes')}
    fields.update(changes)
    return SimpleNamespace(**fields)


def _fake_inventory(monkeypatch, target, *, listed=None, observed=None):
    """Alter the DirEntry listing and/or the os.lstat view of exactly one entry."""
    target = os.path.normcase(os.fspath(target))
    real_lstat, real_scandir = os.lstat, os.scandir

    def selected(path):
        return os.path.normcase(os.fspath(path)) == target

    class Entry:
        def __init__(self, entry):
            self.path, self.name, self._entry = entry.path, entry.name, entry

        def stat(self, *, follow_symlinks=True):
            result = self._entry.stat(follow_symlinks=follow_symlinks)
            return _metadata(result, **listed) if listed is not None and selected(self.path) else result

    @contextlib.contextmanager
    def scandir(directory):
        with real_scandir(directory) as listing:
            yield [Entry(entry) for entry in listing]

    def lstat(path):
        result = real_lstat(path)
        return _metadata(result, **observed) if observed is not None and selected(path) else result

    monkeypatch.setattr(coding, 'os', SimpleNamespace(scandir=scandir, lstat=lstat))


@pytest.mark.parametrize(('target', 'observed', 'message'), [
    ('src/answer.py', {'st_mode': stat.S_IFLNK | 0o777}, _REPARSE),
    ('src/answer.py', {'st_file_attributes': stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_ARCHIVE}, _REPARSE),
    ('src/answer.py', {'st_mode': stat.S_IFDIR | 0o755}, _CHANGED),
    ('src/answer.py', {'st_mode': stat.S_IFIFO | 0o644}, _CHANGED),
    ('src', {'st_mode': stat.S_IFREG | 0o644, 'st_nlink': 1}, _CHANGED),
    ('src/answer.py', {'st_nlink': 2}, _LINKED),
    # A directory-data fallback (link count 0) fails closed.
    ('src/answer.py', {'st_nlink': 0}, _LINKED),
    ('src/answer.py', {'st_size': 8388609}, _OVERSIZE),
])
def test_lstat_metadata_is_rechecked_and_decides_type_links_and_size(tmp_path, monkeypatch, target, observed, message):
    root = _workspace(tmp_path)
    _fake_inventory(monkeypatch, root / safe_path(target), observed=observed)
    with pytest.raises(ValueError, match=message):
        read_workspace(root)


@pytest.mark.parametrize('listed', [
    {'st_mode': stat.S_IFLNK | 0o777},
    {'st_file_attributes': stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_ARCHIVE},
])
def test_direntry_reparse_refusal_is_kept_when_lstat_looks_plain(tmp_path, monkeypatch, listed):
    root = _workspace(tmp_path)
    _fake_inventory(monkeypatch, root / 'src' / 'answer.py', listed=listed)
    with pytest.raises(ValueError, match=_REPARSE):
        read_workspace(root)


@pytest.mark.parametrize('listed', [
    # What os.DirEntry.stat() reports for every file on Windows.
    {'st_nlink': 0},
    {'st_nlink': 2},
    {'st_size': 8388609},
])
def test_listing_link_count_and_size_are_not_trusted(tmp_path, monkeypatch, listed):
    root = _workspace(tmp_path)
    _fake_inventory(monkeypatch, root / 'src' / 'answer.py', listed=listed)
    assert read_workspace(root) == FILES


def test_listing_type_change_is_refused(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    _fake_inventory(monkeypatch, root / 'src' / 'answer.py', listed={'st_mode': stat.S_IFDIR | 0o755})
    with pytest.raises(ValueError, match=_CHANGED):
        read_workspace(root)


def test_consistent_non_regular_entry_is_refused(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    fifo = {'st_mode': stat.S_IFIFO | 0o644}
    _fake_inventory(monkeypatch, root / 'src' / 'answer.py', listed=fifo, observed=fifo)
    with pytest.raises(ValueError, match=_LINKED):
        read_workspace(root)
