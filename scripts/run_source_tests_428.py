"""Worktree-correct, host-lock-serialized source test runner for Pipeline 4.2.8.

Verifies the active Git checkout/commit and isolated module import roots before
executing pytest single-process (-p no:cacheprovider, no -n). Acquires the
shared host lock (C:\\Users\\ansac\\CoChem427\\heavy-run.lock) with a lock-wait
timeout distinct from the child execution timeout, cleans up the owned child
by process handle/PID only, and never releases the host lock while the child
remains active.
"""
from __future__ import annotations

import argparse
import datetime
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Sequence

LOCK_PATH = Path(r'C:\Users\ansac\CoChem427\heavy-run.lock')
HOLDER_PATH = Path(r'C:\Users\ansac\CoChem427\heavy-run.holder.txt')
DEFAULT_PYTHON = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe')
FORBIDDEN_PYTEST_PREFIXES = ('-n', '--numprocesses', '--dist', '--tx', '--forked')
_RETAINED_LOCK_HANDLES: list[object] = []

_CHILD_BOOTSTRAP = """
import json, pathlib, sys
repo = pathlib.Path(sys.argv[1]).resolve()
src = (repo / 'src').resolve()
cleaned = []
for entry in sys.path:
    try:
        resolved = pathlib.Path(entry).resolve()
        if resolved != repo and resolved != src and (
            resolved.name == 'src' or 'Pipeline-Mix-Model-Concurrent' in str(resolved)
        ) and '.venv' not in str(resolved):
            continue
    except OSError:
        pass
    cleaned.append(entry)
sys.path[:] = [str(src), str(repo), *cleaned]
import cochem, cochem_pipeline, cochem_supervisor, pipeline_tests
origins = {}
for mod in (cochem, cochem_pipeline, cochem_supervisor, pipeline_tests):
    mod_path = pathlib.Path(mod.__file__).resolve()
    expected = repo if mod.__name__ == 'pipeline_tests' else src
    if expected not in mod_path.parents:
        raise SystemExit(f'Import root mismatch for {mod.__name__}: {mod_path} is not under {expected}')
    origins[mod.__name__] = str(mod_path)
print('COCHEM_SOURCE_RUNNER_428 ' + json.dumps({
    'checkout': str(repo),
    'src': str(src),
    'origins': origins,
}, sort_keys=True), flush=True)
import pytest
raise SystemExit(pytest.main(sys.argv[2:]))
"""


def validate_pytest_args(pytest_args: Sequence[str]) -> list[str]:
    cleaned = list(pytest_args)
    if cleaned[:1] == ['--']:
        cleaned = cleaned[1:]
    if not cleaned:
        raise ValueError('At least one explicit test file or selection is required')
    for token in cleaned:
        if not isinstance(token, str) or '\x00' in token:
            raise ValueError('Invalid pytest argument')
        if token in FORBIDDEN_PYTEST_PREFIXES or any(
            token.startswith(prefix + '=') or (prefix == '-n' and token.startswith('-n') and len(token) > 2)
            for prefix in FORBIDDEN_PYTEST_PREFIXES
        ):
            raise ValueError(f'Parallel pytest execution is forbidden on AETHERDESK: {token}')
    if '-p' not in cleaned or 'no:cacheprovider' not in cleaned:
        cleaned = ['-p', 'no:cacheprovider', *cleaned]
    return cleaned


def inspect_checkout(repo_root: Path, *, git_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict[str, str]:
    repo = Path(repo_root).resolve()
    src = repo / 'src'
    if not (src / 'cochem_pipeline' / '__init__.py').is_file() or not (repo / 'pipeline_tests').is_dir():
        raise ValueError(f'Invalid pipeline repository layout at {repo}')
    top = git_runner(
        ['git', '-C', str(repo), 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if top.returncode != 0 or not top.stdout.strip():
        raise ValueError(f'Unable to verify Git checkout for {repo}')
    if Path(top.stdout.strip()).resolve() != repo:
        raise ValueError(f'Git toplevel {top.stdout.strip()} does not match requested checkout {repo}')
    head = git_runner(
        ['git', '-C', str(repo), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, timeout=10, check=False,
    )
    commit = head.stdout.strip()
    if head.returncode != 0 or len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError(f'Unable to resolve literal HEAD commit for {repo}')
    branch = git_runner(
        ['git', '-C', str(repo), 'rev-parse', '--abbrev-ref', 'HEAD'],
        capture_output=True, text=True, timeout=10, check=False,
    )
    return {
        'checkout': str(repo),
        'src': str(src),
        'commit': commit,
        'branch': branch.stdout.strip() if branch.returncode == 0 else 'HEAD',
    }


def _cleanup_owned_child(proc, *, grace_seconds: float = 3.0) -> bool:
    """Terminate and kill only the exact owned process handle; never kill by name."""
    if proc.poll() is not None:
        return True
    try:
        proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=max(0.05, grace_seconds))
        return True
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=max(0.05, grace_seconds))
        return True
    except subprocess.TimeoutExpired:
        return proc.poll() is not None


def run_serialized_tests(
    pytest_args: Sequence[str],
    *,
    repo_root: Path | None = None,
    python_exe: Path | None = None,
    lock_path: Path = LOCK_PATH,
    holder_path: Path = HOLDER_PATH,
    lock_timeout_seconds: float = 5400.0,
    timeout_seconds: float = 600.0,
    poll_interval_seconds: float = 0.25,
    grace_seconds: float = 3.0,
    label: str = '',
    popen_factory: Callable[..., object] = subprocess.Popen,
    git_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, dict[str, object]]:
    if type(lock_timeout_seconds) not in (int, float) or not 0 < lock_timeout_seconds <= 86400:
        raise ValueError('lock_timeout_seconds must be in (0, 86400]')
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 7200:
        raise ValueError('timeout_seconds must be in (0, 7200]')
    resolved_repo = Path(repo_root if repo_root is not None else Path(__file__).resolve().parents[1]).resolve()
    verified_args = validate_pytest_args(pytest_args)
    checkout_info = inspect_checkout(resolved_repo, git_runner=git_runner)
    interpreter = Path(python_exe if python_exe is not None else (
        DEFAULT_PYTHON if DEFAULT_PYTHON.is_file() else sys.executable
    )).resolve()
    if not interpreter.is_file():
        raise ValueError(f'Python interpreter not found: {interpreter}')

    lock_path = Path(lock_path)
    holder_path = Path(holder_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, 'a+b')
    deadline = clock() + float(lock_timeout_seconds)
    waited = False
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if clock() >= deadline:
                handle.close()
                holder = holder_path.read_text(encoding='utf-8', errors='replace').strip() if holder_path.exists() else 'unknown'
                sys.stderr.write(
                    f'run_source_tests_428: lock not acquired within {lock_timeout_seconds}s; holder: {holder}\n'
                )
                return 75, {**checkout_info, 'status': 'LOCK_TIMEOUT', 'holder': holder}
            if not waited:
                holder = holder_path.read_text(encoding='utf-8', errors='replace').strip() if holder_path.exists() else 'unknown'
                sys.stderr.write(f'run_source_tests_428: waiting for heavy-run lock (held by: {holder})\n')
                waited = True
            sleeper(min(poll_interval_seconds, max(0.01, deadline - clock())))

    child_stopped = True
    proc = None
    try:
        command = [str(interpreter), '-I', '-c', _CHILD_BOOTSTRAP, str(resolved_repo), *verified_args]
        holder_path.write_text(
            f'pid {os.getpid()} since {datetime.datetime.now():%H:%M:%S} '
            f'checkout {checkout_info["checkout"]} commit {checkout_info["commit"]} '
            f'label {label or "pytest-428"} args {" ".join(verified_args)[:160]}\n',
            encoding='utf-8',
        )
        sys.stdout.write('COCHEM_CHECKOUT_428 ' + json.dumps(checkout_info, sort_keys=True) + '\n')
        sys.stdout.flush()
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        proc = popen_factory(command, cwd=str(resolved_repo), env=env)
        child_stopped = False
        try:
            returncode = proc.wait(timeout=float(timeout_seconds))
            child_stopped = True
            return int(returncode), {
                **checkout_info,
                'status': 'COMPLETED' if returncode == 0 else 'FAILED',
                'returncode': int(returncode),
                'child_pid': getattr(proc, 'pid', None),
                'pytest_args': verified_args,
            }
        except subprocess.TimeoutExpired:
            child_stopped = _cleanup_owned_child(proc, grace_seconds=grace_seconds)
            if not child_stopped:
                raise RuntimeError('Test child remained active after kill; retaining heavy-run.lock')
            return 124, {
                **checkout_info,
                'status': 'CHILD_TIMEOUT',
                'returncode': 124,
                'child_pid': getattr(proc, 'pid', None),
                'cleanup_verified': True,
            }
        except BaseException:
            child_stopped = _cleanup_owned_child(proc, grace_seconds=grace_seconds)
            if not child_stopped:
                raise RuntimeError('Test child remained active after interruption; retaining heavy-run.lock')
            raise
    finally:
        if child_stopped:
            try:
                holder_path.write_text(f'free since {datetime.datetime.now():%H:%M:%S}\n', encoding='utf-8')
            except OSError:
                pass
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()
        else:
            _RETAINED_LOCK_HANDLES.append(handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Worktree-verified serialized pytest runner for 4.2.8.')
    parser.add_argument('--lock-timeout-seconds', type=float, default=5400.0)
    parser.add_argument('--timeout-seconds', type=float, default=600.0)
    parser.add_argument('--label', default='pytest-428')
    parser.add_argument('--repo-root', type=Path, default=None)
    parser.add_argument('--python', type=Path, default=None)
    parser.add_argument('pytest_args', nargs=argparse.REMAINDER)
    args, unknown = parser.parse_known_args(argv)
    combined = [*unknown, *args.pytest_args]
    code, _ = run_serialized_tests(
        combined,
        repo_root=args.repo_root,
        python_exe=args.python,
        lock_timeout_seconds=args.lock_timeout_seconds,
        timeout_seconds=args.timeout_seconds,
        label=args.label,
    )
    return code


if __name__ == '__main__':
    raise SystemExit(main())
