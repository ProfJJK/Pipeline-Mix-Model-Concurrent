"""In-process Win32 handles on pytest-owned temporary files only.

No children, providers, SYSTEM tokens, profile data, ACL edits or host tasks.
ACL/profile lookup are inert fixtures; actual sharing enforcement is exercised.
"""
import ctypes as C
from ctypes import wintypes as W
import os
from types import SimpleNamespace

import pytest

from cochem_pipeline.agy_agent_guard import lock_worker_profile
from cochem_pipeline.r6_agent_acceptance import discovery_paths
from pipeline_tests.test_agy_agent_guard import fixture

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows sharing semantics')


def kernel():
    api = C.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    api.CreateFileW.restype = W.HANDLE
    api.CloseHandle.argtypes, api.CloseHandle.restype = [W.HANDLE], W.BOOL
    return api


@pytest.mark.parametrize('implementation', ['source', 'installed-r6-amendment'])
def test_production_directory_handles_block_replacement_then_restore_access(tmp_path, implementation):
    lock = lock_worker_profile
    if implementation == 'installed-r6-amendment':
        from pathlib import Path
        from scripts.r6_custody_amendment import repaired_module
        raw = (Path(__file__).parent / 'fixtures/r6_agy_agent_guard_359ca92.txt').read_bytes()
        module, _ = repaired_module(raw)
        lock = module.lock_worker_profile
    contract, _, _, backend = fixture(tmp_path)
    api = kernel()
    def close(handle):
        assert api.CloseHandle(handle)
    def profile(token, buffer, size):
        size._obj.value = len(str(tmp_path)) + 1
        if buffer is not None:
            buffer.value = str(tmp_path)
        return True
    win = SimpleNamespace(require_system=lambda: None, DWORD=W.DWORD, WindowsIsolationError=RuntimeError,
        _api=lambda: {'kernel32': api, 'userenv': SimpleNamespace(GetUserProfileDirectoryW=profile)},
        _check=lambda result, label: result, _close=close, _acl=backend['acl'])
    requests = [(p, 0x10000) for p in discovery_paths(tmp_path)]
    requests += [(p, 0x40000000) for p in discovery_paths(tmp_path) if p.name == 'agent.md']
    def probe():
        results = []
        for path, access in requests:
            handle = api.CreateFileW(str(path), access, 7, None, 3, 0x02200000, None)
            if handle in (None, 0, C.c_void_p(-1).value):
                results.append(C.get_last_error())
            else:
                close(handle)
                results.append(0)
        return results
    assert probe() == [0] * 11
    guard = lock(win, 'fixture-token', 'worker-sid', contract)
    try:
        assert len(guard.handles) == 9
        assert probe() == [32] * 11
        # Readers still work; the production scanner reads both pinned files.
        for path, _ in requests[-2:]:
            assert path.read_bytes() == b'reviewed agent fixture\n'
    finally:
        guard.close()
    assert probe() == [0] * 11
