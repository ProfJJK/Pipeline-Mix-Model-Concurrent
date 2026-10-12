"""Retained, SYSTEM-only input custody for future R7 catalog activation.

No API accepts an authority pathname, and importing this module opens nothing.
The caller must retain the context through probing and durable publication.
Reading authority is not native acceptance or permission to bypass slot limits.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import stat

from .catalog_activation import CatalogChange, decode_proposal
from .routing import _strict_json

AUTHORITY_ROOT = Path(r'C:\Program Files\CoChem\RoutingCatalog4.2.7')


@dataclass(frozen=True)
class CatalogAuthority:
    request_id: str
    pointer_sha256: str
    proposal_sha256: str
    change: CatalogChange


@contextmanager
def _read_locked(root, current, backend, resolver=None):
    """Injection boundary for ordinary-path fixtures, never a controller endpoint."""
    root = Path(root)
    if not root.is_absolute():
        raise ValueError('Catalog authority root must be absolute')
    handles = []
    try:
        # Hold ancestors top-down against replacement before inspecting children.
        # Directories still allow unrelated normal writes; files allow only reads.
        for directory in (*reversed(root.parents), root):
            handles.append(backend.acquire(directory, True))
            backend.inspect(directory, True)
        backend.validate(root)

        def read_file(path, maximum):
            handles.append(backend.acquire(path, False))
            size = backend.inspect(path, False)
            if not 1 <= size <= maximum:
                raise ValueError('Catalog authority file exceeds bounds')
            backend.validate(path)
            data = backend.read(path, maximum + 1)
            if len(data) != size:
                raise ValueError('Catalog authority file changed while held')
            return data

        data = read_file(root/'current-request.json', 4096)
        pointer = _strict_json(data.decode('utf-8'))
        if (not isinstance(pointer, dict)
                or set(pointer) != {'schema', 'request_id', 'proposal_sha256'}
                or pointer['schema'] != 'cochem-catalog-authority-pointer/1'
                or not isinstance(pointer['request_id'], str)
                or not re.fullmatch('[a-f0-9]{32}', pointer['request_id'])
                or not isinstance(pointer['proposal_sha256'], str)
                or not re.fullmatch('[a-f0-9]{64}', pointer['proposal_sha256'])):
            raise ValueError('Invalid protected catalog pointer')
        # A digest-derived leaf eliminates supplied absolute/traversal paths.
        proposal = read_file(root/(pointer['proposal_sha256']+'.json'), 1024*1024)
        if resolver is not None:
            previous=_strict_json(proposal.decode('utf-8')).get('previous_policy_digest')
            current=resolver(previous)
        change = decode_proposal(proposal, current, expected_sha256=pointer['proposal_sha256'])
        yield CatalogAuthority(pointer['request_id'], hashlib.sha256(data).hexdigest(),
            pointer['proposal_sha256'], change)
    finally:
        for handle in reversed(handles):
            backend.release(handle)


class _WindowsCustody:
    def __init__(self, win):
        self.win = win
        self.api = win._api()

    def acquire(self, path, directory):
        import ctypes
        handle = self.api['kernel32'].CreateFileW(str(path), 0x20000 if directory else 0x80000000,
            3 if directory else 1, None, 3, 0x02200000, None)
        if handle in (None, 0, ctypes.c_void_p(-1).value):
            raise self.win.WindowsIsolationError('Catalog authority path cannot be retained')
        return handle

    def inspect(self, path, directory):
        info = path.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                or (directory and not stat.S_ISDIR(info.st_mode))
                or (not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))):
            raise self.win.WindowsIsolationError('Catalog authority contains a redirected or linked object')
        return info.st_size

    def validate(self, path):
        self.win.validate_code_path(path)

    def read(self, path, maximum):
        with path.open('rb') as stream:
            return stream.read(maximum)

    def release(self, handle):
        self.win._close(handle)


@contextmanager
def protected_catalog_request(current, resolver=None):
    from . import windows as win
    win.require_system()
    with _read_locked(AUTHORITY_ROOT, current, _WindowsCustody(win), resolver) as authority:
        yield authority
