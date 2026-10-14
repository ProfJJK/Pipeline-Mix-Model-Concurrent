"""Inert unit and lock tests for scripts/run_source_tests_428.py (P428-00)."""
from __future__ import annotations

import json
import msvcrt
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.run_source_tests_428 import (
    _CHILD_BOOTSTRAP,
    _RETAINED_LOCK_HANDLES,
    LOCK_PATH,
    inspect_checkout,
    run_serialized_tests,
    validate_pytest_args,
)


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'worktree-a'
    for pkg in ('cochem', 'cochem_pipeline', 'cochem_supervisor'):
        pkg_dir = repo / 'src' / pkg
        pkg_dir.mkdir(parents=True)
        (pkg_dir / '__init__.py').write_text('__version__ = "4.2.8"\n', encoding='utf-8')
    tests_dir = repo / 'pipeline_tests'
    tests_dir.mkdir(parents=True)
    (tests_dir / '__init__.py').write_text('', encoding='utf-8')
    return repo


def _fake_git(repo: Path, commit: str = 'a' * 40, toplevel: Path | None = None):
    top = str((toplevel or repo).resolve())
    def runner(cmd, **kwargs):
        if '--show-toplevel' in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=top + '\n', stderr='')
        if '--abbrev-ref' in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='feature/4.2.8-task-routing\n', stderr='')
        return subprocess.CompletedProcess(cmd, 0, stdout=commit + '\n', stderr='')
    return runner


class _FakeProc:
    def __init__(self, *, returncode=0, timeout_on_first_wait=False, refuse_to_die=False):
        self.pid = 42800
        self._returncode = returncode
        self._timeout_on_first_wait = timeout_on_first_wait
        self._refuse_to_die = refuse_to_die
        self.terminated = False
        self.killed = False
        self._exited = not timeout_on_first_wait

    def poll(self):
        return self._returncode if self._exited else None

    def wait(self, timeout=None):
        if self._timeout_on_first_wait and not self.terminated and not self.killed:
            raise subprocess.TimeoutExpired(cmd=['pytest'], timeout=timeout or 1.0)
        if self._refuse_to_die:
            raise subprocess.TimeoutExpired(cmd=['pytest'], timeout=timeout or 1.0)
        self._exited = True
        return self._returncode

    def terminate(self):
        self.terminated = True
        if not self._refuse_to_die:
            self._exited = True
            self._returncode = -15

    def kill(self):
        self.killed = True
        if not self._refuse_to_die:
            self._exited = True
            self._returncode = -9


def test_default_lock_path_is_shared_host_lock():
    assert LOCK_PATH == Path(r'C:\Users\ansac\CoChem427\heavy-run.lock')


@pytest.mark.parametrize('bad_args', [
    [],
    ['--'],
    ['-n', '4', 'pipeline_tests/test_config.py'],
    ['-n2', 'pipeline_tests/test_config.py'],
    ['--numprocesses=2', 'pipeline_tests/test_config.py'],
    ['--dist=loadscope', 'pipeline_tests/test_config.py'],
    ['--forked', 'pipeline_tests/test_config.py'],
])
def test_validate_pytest_args_rejects_parallel_or_empty_invocations(bad_args):
    with pytest.raises(ValueError):
        validate_pytest_args(bad_args)


def test_validate_pytest_args_enforces_no_cacheprovider():
    args = validate_pytest_args(['--', 'pipeline_tests/test_workflow_428.py', '-k', 'not real'])
    assert args[:2] == ['-p', 'no:cacheprovider']
    assert 'pipeline_tests/test_workflow_428.py' in args


def test_inspect_checkout_verifies_toplevel_and_commit(tmp_path):
    repo = _fake_repo(tmp_path)
    info = inspect_checkout(repo, git_runner=_fake_git(repo, commit='b' * 40))
    assert info['checkout'] == str(repo.resolve())
    assert info['commit'] == 'b' * 40
    assert info['branch'] == 'feature/4.2.8-task-routing'

    other = tmp_path / 'other-checkout'
    other.mkdir()
    with pytest.raises(ValueError, match='does not match'):
        inspect_checkout(repo, git_runner=_fake_git(repo, toplevel=other))

    with pytest.raises(ValueError, match='HEAD commit'):
        inspect_checkout(repo, git_runner=_fake_git(repo, commit='not-a-sha'))


def test_lock_wait_timeout_is_distinct_and_does_not_spawn_child(tmp_path):
    repo = _fake_repo(tmp_path)
    lock_file = tmp_path / 'heavy-run.lock'
    holder_file = tmp_path / 'heavy-run.holder.txt'
    holder_file.write_text('pid 9999 label other-worktree\n', encoding='utf-8')
    held = open(lock_file, 'a+b')
    held.seek(0)
    msvcrt.locking(held.fileno(), msvcrt.LK_NBLCK, 1)
    spawned = []
    clock = [0.0]

    def advance(dt):
        clock[0] += dt

    try:
        code, meta = run_serialized_tests(
            ['pipeline_tests/test_workflow_428.py'],
            repo_root=repo,
            python_exe=Path(sys.executable),
            lock_path=lock_file,
            holder_path=holder_file,
            lock_timeout_seconds=1.0,
            timeout_seconds=60.0,
            popen_factory=lambda *a, **kw: spawned.append(a) or _FakeProc(),
            git_runner=_fake_git(repo),
            clock=lambda: clock[0],
            sleeper=advance,
        )
        assert code == 75
        assert meta['status'] == 'LOCK_TIMEOUT'
        assert not spawned
    finally:
        held.seek(0)
        msvcrt.locking(held.fileno(), msvcrt.LK_UNLCK, 1)
        held.close()


def test_child_timeout_cleans_up_owned_handle_and_releases_lock(tmp_path):
    repo = _fake_repo(tmp_path)
    lock_file = tmp_path / 'heavy-run.lock'
    holder_file = tmp_path / 'heavy-run.holder.txt'
    proc = _FakeProc(timeout_on_first_wait=True)

    code, meta = run_serialized_tests(
        ['pipeline_tests/test_workflow_428.py'],
        repo_root=repo,
        python_exe=Path(sys.executable),
        lock_path=lock_file,
        holder_path=holder_file,
        lock_timeout_seconds=5.0,
        timeout_seconds=0.5,
        grace_seconds=0.05,
        popen_factory=lambda *a, **kw: proc,
        git_runner=_fake_git(repo),
    )
    assert code == 124
    assert meta['status'] == 'CHILD_TIMEOUT'
    assert meta['cleanup_verified'] is True
    assert proc.terminated is True
    assert 'free since' in holder_file.read_text(encoding='utf-8')


def test_uncleaned_child_retains_host_lock(tmp_path):
    repo = _fake_repo(tmp_path)
    lock_file = tmp_path / 'heavy-run.lock'
    holder_file = tmp_path / 'heavy-run.holder.txt'
    proc = _FakeProc(timeout_on_first_wait=True, refuse_to_die=True)

    with pytest.raises(RuntimeError, match='retaining heavy-run.lock'):
        run_serialized_tests(
            ['pipeline_tests/test_workflow_428.py'],
            repo_root=repo,
            python_exe=Path(sys.executable),
            lock_path=lock_file,
            holder_path=holder_file,
            lock_timeout_seconds=5.0,
            timeout_seconds=0.2,
            grace_seconds=0.05,
            popen_factory=lambda *a, **kw: proc,
            git_runner=_fake_git(repo),
        )
    assert proc.terminated and proc.killed
    probe = open(lock_file, 'a+b')
    try:
        probe.seek(0)
        with pytest.raises(OSError):
            msvcrt.locking(probe.fileno(), msvcrt.LK_NBLCK, 1)
    finally:
        probe.close()
        while _RETAINED_LOCK_HANDLES:
            retained = _RETAINED_LOCK_HANDLES.pop()
            retained.seek(0)
            msvcrt.locking(retained.fileno(), msvcrt.LK_UNLCK, 1)
            retained.close()


def test_bootstrap_strips_competing_checkout_src_paths():
    assert 'Pipeline-Mix-Model-Concurrent' in _CHILD_BOOTSTRAP
    assert 'Import root mismatch' in _CHILD_BOOTSTRAP
