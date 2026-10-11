"""End only the exact owned, stalled publication-test child; preserve parent.

No broad process termination: username, unique harness argv, parent relationship,
exact pytest argv, creation time and held native image/creation proof are checked.
"""
import ctypes
from ctypes import wintypes
import getpass
import json
from pathlib import Path
import sys

import psutil

ROOT = Path(r"C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next")
RUN = ROOT / "publication-validation-20261009-4723f9a40a664b9a943e7c6d80b0a8f2"
HARNESS = ROOT / "run_publication_validation_20261009.py"
BASE = Path(r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe")
ARGS = [str(RUN / "venv/Scripts/python.exe"), "-I", "-m", "pytest", "pipeline_tests", "mcp_tests", "supervisor_tests", "-q", "-p", "no:cacheprovider", "--basetemp=" + str(RUN / "pytest-scratch"), "--junitxml=" + str(RUN / "publication-canonical-windows-tests.xml")]


def equivalent(left, right):
    return len(left) == len(right) and all(a.replace("/", "\\").casefold() == b.replace("/", "\\").casefold() for a, b in zip(left, right))


def main():
    myself = psutil.Process()
    owner = myself.username()
    parents = []
    for item in psutil.process_iter(["pid", "name"]):
        try:
            if item.info["name"].casefold() != "python.exe" or item.username().casefold() != owner.casefold():
                continue
            args = item.cmdline()
            if equivalent(args, [str(BASE), "-I", str(HARNESS)]):
                parents.append(item)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    assert len(parents) == 1, "Exact owned test harness was not unique"
    parent = parents[0]
    children = [item for item in parent.children() if equivalent(item.cmdline(), ARGS)]
    assert len(children) == 1, "Exact direct pytest child was not unique"
    child = children[0]
    assert child.pid != 5788 and child.ppid() == parent.pid and child.username().casefold() == owner.casefold()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    creation_expected = child.create_time()
    handle = kernel.OpenProcess(0x1000 | 0x100000 | 1, False, child.pid)
    assert handle, "Could not retain exact own fixture process handle"
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        assert kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times])
        created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) / 10000000 - 11644473600
        assert abs(created - creation_expected) < 0.001
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        assert kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length))
        assert Path(buffer.value).resolve() == (RUN / "venv/Scripts/python.exe").resolve()
        assert equivalent(child.cmdline(), ARGS) and child.ppid() == parent.pid
        descendants = child.children(recursive=True)
        assert len(descendants) <= 8
        for item in descendants:
            assert item.pid != 5788 and item.username().casefold() == owner.casefold()
        assert kernel.TerminateProcess(handle, 124)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
        gone, remaining = psutil.wait_procs(descendants, timeout=5)
        assert not remaining, "Owned redirector descendants did not finish; no broader cleanup performed"
        report = {"schema": "cochem-owned-publication-fixture-stop/1", "harness_pid": parent.pid, "test_child_pid": child.pid, "test_child_creation_unix": created, "image_verified": True, "exact_arguments_verified": True, "native_handle_retained": True, "owned_descendants_exited": len(gone), "production_process_modified": False, "reason": "Canonical suite stalled over 180 seconds in in-memory MCP fixture; partial log preserved", "run_root": str(RUN)}
        with (RUN / "owned-fixture-stop.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps(report))
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    main()
