"""Verify robocopy backup-mode copies of the private SQLite stores (r4 retarget, v3).

Usage: python -I -B backup-private-databases-r4.py <destination>

The private root (C:\\ProgramData\\CoChemPipeline427\\private) carries a SYSTEM-only DACL, so
the elevated owner cannot read it directly and must not open it with SQLite: a read-only
open of a cleanly closed WAL database still creates -wal and -shm files beside the source.
The PowerShell driver therefore copies *.db, *.db-wal and *.db-journal with
`robocopy /B` (backup semantics, sources opened read-only) into <destination>, and this
helper touches only the copies: it opens each copy read-write so SQLite recovers the copied
WAL frames (or rolls back a copied hot journal), checkpoints and truncates the copy's WAL,
runs integrity_check, lists the tables and fingerprints the resulting single file.

Standard library only. Exit 0 with a JSON report on stdout; exit 1 with a reason on stderr.
The destination is never created here and existing verification output is never overwritten.
"""
import hashlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

SCHEMA = 'cochem-private-database-backup/3'
KNOWN = ('job_board.db', 'containers\\containers.db', 'oracle\\tracking.db', 'operations\\objectives.db')
REQUIRED = ('job_board.db',)
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
CHUNK = 1024 * 1024


def fail(reason: str) -> None:
    sys.stderr.write(reason + '\n')
    sys.exit(1)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def is_reparse(path: Path) -> bool:
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
    except AttributeError:  # non-Windows interpreter: nothing to refuse
        return os.path.islink(path)
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def discover_copies(destination: Path) -> list[Path]:
    copies = []
    for root, dirs, files in os.walk(destination):
        root_path = Path(root)
        if is_reparse(root_path):
            fail('REPARSE_IN_DESTINATION:' + str(root_path))
        dirs.sort()
        for name in sorted(files):
            candidate = root_path / name
            if is_reparse(candidate):
                fail('REPARSE_IN_DESTINATION:' + str(candidate))
            if name.lower().endswith('.db-shm'):
                fail('SHM_COPIED:' + str(candidate))
            if name.lower().endswith('.db'):
                copies.append(candidate)
    return copies


def verify_copy(destination: Path, copy: Path) -> dict:
    relative = str(copy.relative_to(destination))
    wal = Path(str(copy) + '-wal')
    journal = Path(str(copy) + '-journal')
    entry = {
        'relative': relative,
        'known': relative.lower() in {name.lower() for name in KNOWN},
        'backup_path': str(copy),
        'copied_bytes': copy.stat().st_size,
        'wal_copied': wal.exists(),
        'wal_copied_bytes': wal.stat().st_size if wal.exists() else 0,
        'journal_copied': journal.exists(),
    }
    for companion in (copy, wal, journal):  # a read-only source attribute must not survive onto the copy
        if companion.exists():
            os.chmod(companion, stat.S_IREAD | stat.S_IWRITE)
    connection = sqlite3.connect(str(copy), isolation_level=None)
    try:
        entry['journal_mode'] = connection.execute('PRAGMA journal_mode').fetchone()[0]
        # The copied WAL frames are already recovered by the first read above; the checkpoint
        # row is the raw PRAGMA result (often 0,0,0 after recovery), not a frame count claim.
        # Evidence of recovery is wal_copied_bytes together with wal_after_close_bytes == 0.
        busy, log_frames, checkpointed = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        entry['checkpoint_truncate_raw'] = {'busy': busy, 'log': log_frames, 'checkpointed': checkpointed}
        if busy:
            fail('CHECKPOINT_BUSY:' + relative)
        integrity = [row[0] for row in connection.execute('PRAGMA integrity_check')]
        entry['integrity'] = 'ok' if integrity == ['ok'] else 'failed'
        entry['integrity_detail'] = integrity[:10]
        entry['tables'] = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        entry['page_count'] = connection.execute('PRAGMA page_count').fetchone()[0]
    except sqlite3.DatabaseError as error:
        fail('COPY_UNREADABLE:' + relative + ':' + str(error))
    finally:
        connection.close()
    if entry['integrity'] != 'ok':
        fail('INTEGRITY_FAILED:' + relative)
    entry['wal_after_close_bytes'] = wal.stat().st_size if wal.exists() else 0
    entry['verified_bytes'] = copy.stat().st_size
    entry['sha256_after_checkpoint'] = sha256_of(copy)
    return entry


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        fail('USAGE: backup-private-databases-r4.py <destination>')
    destination = Path(argv[1])
    if not destination.is_dir() or is_reparse(destination):
        fail('DESTINATION_NOT_A_DIRECTORY:' + str(destination))
    report_path = destination / 'verification.json'
    if report_path.exists():
        fail('VERIFICATION_EXISTS:' + str(report_path))
    copies = discover_copies(destination)
    total = sum(copy.stat().st_size + (Path(str(copy) + '-wal').stat().st_size if Path(str(copy) + '-wal').exists() else 0)
                for copy in copies)
    if total > MAX_TOTAL_BYTES:
        fail('BACKUP_TOO_LARGE:' + str(total))
    entries = [verify_copy(destination, copy) for copy in copies]
    present = {entry['relative'].lower() for entry in entries}
    for name in REQUIRED:
        if name.lower() not in present:
            fail('REQUIRED_STORE_MISSING:' + name)
    report = {
        'schema': SCHEMA,
        'destination': str(destination),
        'sources_opened': False,
        'copy_mode': 'robocopy backup semantics by the driver; this helper verifies copies only',
        'known_stores': [{'relative': name, 'present': name.lower() in present} for name in KNOWN],
        'other_stores': sorted(entry['relative'] for entry in entries if not entry['known']),
        'databases': entries,
        'total_copied_bytes': total,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    with report_path.open('x', encoding='utf-8') as handle:
        handle.write(text + '\n')
    sys.stdout.write(text + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
