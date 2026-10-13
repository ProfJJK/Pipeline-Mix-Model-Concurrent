"""Pin Agy's reviewed agent paths for the lifetime of one owned native tree.

No ACLs or profile data are changed. Open directory handles deny delete sharing,
so writable ancestors cannot rename the protected discovery folders between the
preflight check and Agy reading them. File handles also deny write sharing.
"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import re
import stat


RELATIVES = ('.gemini/agents/cochem-inference-only/agent.md',
             '.gemini/config/agents/cochem-inference-only/agent.md')
FULL = 0x1F01FF
READ_FILE, READ_DIRECTORY = 0x120089, 0x1200A9


class AgentGuardError(ValueError):
    category = 'compatibility'


def validate_contract(raw):
    if (not isinstance(raw, dict) or set(raw) != {'name', 'sha256', 'bytes', 'relative_paths'}
            or raw['name'] != 'cochem-inference-only' or raw['relative_paths'] != list(RELATIVES)
            or not isinstance(raw['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', raw['sha256'])
            or type(raw['bytes']) is not int or not 1 <= raw['bytes'] <= 4096):
        raise ValueError('Agy requires the pinned inference-only agent definition at both reviewed paths')
    return dict(raw)


def require_agent_contract(spec):
    from .inference_policy import gemini_inference_arguments
    contract = validate_contract(spec.get('agent_definition'))
    arguments = gemini_inference_arguments(spec)
    if (arguments.count('--agent') != 1 or arguments.index('--agent') + 1 >= len(arguments)
            or arguments[arguments.index('--agent') + 1] != contract['name']
            or any(argument.startswith('--agent=') for argument in arguments)):
        raise ValueError('Agy invocation must select the same reviewed, guarded agent')
    return contract


class AgentPathGuard:
    def __init__(self, release):
        self.handles = []
        self.release = release

    def close(self):
        while self.handles:
            self.release(self.handles.pop())


def lock_verified_tree(profile, sid, contract, *, acquire, release, acl):
    """Shared filesystem logic. The native entry point supplies held Win32 handles.

    Tests may supply inert handle/ACL fixtures; they do not attest native denial.
    """
    contract = validate_contract(contract)
    profile = Path(profile)
    guard = AgentPathGuard(release)
    seen = set()
    try:
        for relative in RELATIVES:
            parts = Path(relative).parts
            paths = [profile, *(profile.joinpath(*parts[:n]) for n in range(1, len(parts) + 1))]
            for path in paths:
                if path in seen:
                    continue
                directory = path.name != 'agent.md'
                guard.handles.append(acquire(path, directory))
                info = os.lstat(path)
                if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                        or (directory and not stat.S_ISDIR(info.st_mode))
                        or (not directory and not stat.S_ISREG(info.st_mode))):
                    raise ValueError('Agy agent path contains a link or unexpected object')
                seen.add(path)
                # The worker may write its profile/config root. The discovery
                # parent, leaf and file must have the exact protected ACL.
                if path.name in ('agents', 'cochem-inference-only', 'agent.md'):
                    owner, protected, rules = acl(path)
                    flags = 3 if directory else 0
                    expected = {('S-1-5-18', FULL, flags), ('S-1-5-32-544', FULL, flags),
                                (sid, READ_DIRECTORY if directory else READ_FILE, flags)}
                    if owner != 'S-1-5-18' or not protected or len(rules) != 3 or set(rules) != expected:
                        raise ValueError('Agy agent discovery ACL differs from the protected staging contract')
                if not directory:
                    if info.st_nlink != 1 or info.st_size != contract['bytes']:
                        raise ValueError('Agy agent file identity or length differs')
                    with path.open('rb') as stream:
                        data = stream.read(4097)
                    if len(data) != contract['bytes'] or hashlib.sha256(data).hexdigest() != contract['sha256']:
                        raise ValueError('Agy agent definition bytes differ from their protected pin')
        return guard
    except BaseException:
        guard.close()
        raise


def lock_worker_profile(win, token, sid, contract):
    win.require_system()
    validate_contract(contract)
    api = win._api()

    def acquire(path, directory):
        # Non-inheritable handles; OPEN_REPARSE_POINT prevents following a link.
        # Directories allow normal writes but never deletion/rename. Agent files
        # allow readers only. All handles survive until verified native teardown.
        # READ_CONTROL alone is metadata access and does not participate in
        # Windows read/write/delete sharing checks. FILE_LIST_DIRECTORY (1)
        # makes the retained directory handle enforce the missing SHARE_DELETE.
        handle = api['kernel32'].CreateFileW(str(path), 0x20001 if directory else 0x80000000,
                    3 if directory else 1, None, 3, 0x02200000, None)
        if handle in (None, 0, C.c_void_p(-1).value):
            raise ValueError('Agy agent path could not be held against replacement')
        return handle

    try:
        size = win.DWORD()
        api['userenv'].GetUserProfileDirectoryW(token, None, C.byref(size))
        if not 1 <= size.value <= 32768:
            raise ValueError('Agy worker profile path is unavailable')
        buffer = C.create_unicode_buffer(size.value)
        win._check(api['userenv'].GetUserProfileDirectoryW(token, buffer, C.byref(size)), 'Read owned worker profile path')
        return lock_verified_tree(Path(buffer.value), sid, contract,
                                  acquire=acquire, release=win._close, acl=win._acl)
    except (ValueError, OSError, win.WindowsIsolationError) as exc:
        raise AgentGuardError('Reviewed Agy agent custody could not be verified; no native launch') from exc
