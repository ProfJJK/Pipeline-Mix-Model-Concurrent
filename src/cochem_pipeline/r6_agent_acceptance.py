"""Owner-run SYSTEM acceptance of retained Agy discovery-path handles.

No agent is launched, no path is renamed, and no data is written. Access checks
request handles only. The controller holds the production guard while the
current thread impersonates each existing restricted worker, sequentially.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path

from .agy_agent_guard import RELATIVES, lock_worker_profile, require_agent_contract


def discovery_paths(profile):
    paths = []
    for relative in RELATIVES:
        parts = Path(relative).parts
        for path in [profile, *(profile.joinpath(*parts[:n]) for n in range(1, len(parts) + 1))]:
            if path not in paths:
                paths.append(path)
    return paths


def verify_worker(api, identity, contract):
    """The adapter owns native tokens/impersonation; tests use inert adapters."""
    token = api.token(identity)
    guard = None
    try:
        profile, sid = api.profile(token), api.sid(identity)
        paths = discovery_paths(profile)
        if len(paths) != 9:
            raise ValueError('Unexpected Agy discovery path topology')
        # Compare the same access requests before, during and after custody.
        # A worker-writable ancestor must succeed before and after; a protected
        # path may remain ACL-denied. A missing path never counts as a denial.
        requests = [(path, 0x10000, path.name != 'agent.md') for path in paths]
        requests += [(path, 0x40000000, False) for path in paths if path.name == 'agent.md']
        before = api.check(token, requests)
        if len(before) != len(requests) or any(code not in (0, 5) for code in before):
            raise ValueError('Pre-existing contention or an invalid discovery path')
        if before[0] != 0:
            raise ValueError('Profile control did not demonstrate worker delete access')
        guard = api.guard(token, sid, contract)
        if len(guard.handles) != 9:
            raise ValueError('Production guard did not retain every discovery path')
        during = api.check(token, requests)
        if len(during) != len(requests) or any(code not in (5, 32) for code in during):
            raise ValueError('Worker obtained replacement/write access during custody')
        guard.close()
        guard = None
        after = api.check(token, requests)
        if after != before:
            raise ValueError('Access did not return to its original state after guard cleanup')
        return dict(paths=9, handle_requests=len(requests), before=before, held=during,
            after=after, replacement_denied=True, cleanup_verified=True,
            path_mutations=0, native_model_jobs_executed=0)
    finally:
        if guard is not None:
            guard.close()
        api.close_token(token)


class WindowsChecks:
    def __init__(self):
        from . import windows as win
        win.require_system()
        self.win, self.api = win, win._api()
        self.impersonate = self.api['advapi32'].ImpersonateLoggedOnUser
        self.impersonate.argtypes, self.impersonate.restype = [win.HANDLE], win.BOOL
        self.revert = self.api['advapi32'].RevertToSelf
        self.revert.argtypes, self.revert.restype = [], win.BOOL

    def token(self, identity):
        return self.win._worker_token(self.win.WorkerIdentity(**identity))

    def close_token(self, token):
        self.win._close(token)

    def sid(self, identity):
        return self.win._sid_text(self.win._account_sid(identity['name']))

    def profile(self, token):
        size = self.win.DWORD()
        self.api['userenv'].GetUserProfileDirectoryW(token, None, C.byref(size))
        if not 1 <= size.value <= 32768:
            raise ValueError('Profile path exceeds bounds')
        buffer = C.create_unicode_buffer(size.value)
        self.win._check(self.api['userenv'].GetUserProfileDirectoryW(token, buffer, C.byref(size)), 'Read profile path')
        return Path(buffer.value)

    def guard(self, token, sid, contract):
        return lock_worker_profile(self.win, token, sid, contract)

    def check(self, token, requests):
        codes = []
        self.win._check(self.impersonate(token), 'Impersonate restricted worker for handle checks')
        try:
            for path, access, directory in requests:
                handle = self.api['kernel32'].CreateFileW(str(path), access, 7, None, 3,
                    0x00200000 | (0x02000000 if directory else 0), None)
                if handle in (None, 0, C.c_void_p(-1).value):
                    codes.append(C.get_last_error())
                else:
                    self.win._close(handle)
                    codes.append(0)
        finally:
            # A failed reversion must never return to privileged setup code.
            if not self.revert():
                raise RuntimeError('Impersonation reversion failed; terminate this one-shot task')
        return codes


def accept(config, *, api=None):
    contract = require_agent_contract(config.providers['gemini'])
    if len(config.workers) != 6 or config.max_execution_slots != 4:
        raise ValueError('RG4 requires all six configured identities and four shared slots')
    api = WindowsChecks() if api is None else api
    results = {}
    for slot, identity in sorted(config.workers.items()):
        results[slot] = verify_worker(api, identity, contract)
    return dict(schema='cochem-r6-agent-custody-acceptance/1',
        status='SIX_WORKER_AGENT_CUSTODY_VERIFIED', workers=results,
        native_model_jobs_executed=0, path_mutations=0, activation_ready=False)
