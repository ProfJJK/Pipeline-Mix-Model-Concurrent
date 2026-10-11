"""Run one heavy command (a test suite, a harness, a build) only when no other agent is running one.

AGENTS.md forbids several agents or subagents running test suites or builds at the same time on this host.
Every such run goes through this wrapper:

    python -I serialize-heavy.py [--timeout-minutes N] [--label TEXT] -- <command> [args...]

It takes an exclusive lock on C:\\Users\\ansac\\CoChem427\\heavy-run.lock (waiting up to the timeout),
records the holder, runs the command with the inherited console, releases the lock, and exits with the
command's exit code. The lock is released by the operating system if the process dies.
"""
import argparse
import datetime
import msvcrt
import os
import subprocess
import sys
import time
from pathlib import Path

LOCK_PATH = Path(r'C:\Users\ansac\CoChem427\heavy-run.lock')
HOLDER_PATH = Path(r'C:\Users\ansac\CoChem427\heavy-run.holder.txt')


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument('--timeout-minutes', type=float, default=90.0)
    parser.add_argument('--label', default='')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a command is required after --')
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_PATH, 'a+b')
    deadline = time.monotonic() + args.timeout_minutes * 60
    waited = False
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if time.monotonic() >= deadline:
                holder = HOLDER_PATH.read_text(encoding='utf-8', errors='replace') if HOLDER_PATH.exists() else 'unknown'
                sys.stderr.write(f'serialize-heavy: lock not acquired within {args.timeout_minutes} min; holder: {holder}\n')
                return 75
            if not waited:
                holder = HOLDER_PATH.read_text(encoding='utf-8', errors='replace') if HOLDER_PATH.exists() else 'unknown'
                sys.stderr.write(f'serialize-heavy: waiting for the heavy-run lock (held by: {holder.strip()})\n')
                waited = True
            time.sleep(3)
    try:
        HOLDER_PATH.write_text(f'pid {os.getpid()} since {datetime.datetime.now():%H:%M:%S} label {args.label} command {" ".join(command)[:200]}\n', encoding='utf-8')
        return subprocess.run(command).returncode
    finally:
        try:
            HOLDER_PATH.write_text(f'free since {datetime.datetime.now():%H:%M:%S}\n', encoding='utf-8')
        except OSError:
            pass
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


if __name__ == '__main__':
    sys.exit(main())
