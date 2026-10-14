"""Ordinary temp files with injected custody; never invokes Win32/SYSTEM calls."""
import hashlib
import json
import stat
from types import SimpleNamespace

import pytest

from cochem_pipeline.catalog_authority import _read_locked, protected_catalog_request
from cochem_pipeline.routing import load_routing_policy


class Custody:
    def __init__(self):
        self.held=[];self.opened=[];self.closed=[];self.validated=[];self.fail=None
    def acquire(self,path,directory):
        if self.fail==('acquire',path.name):raise ValueError('fixture denied')
        self.held.append(path);self.opened.append(path);return path
    def inspect(self,path,directory):
        assert path in self.held
        if self.fail==('inspect',path.name):raise ValueError('fixture redirect')
        return path.stat().st_size
    def validate(self,path):
        assert path in self.held
        if self.fail==('validate',path.name):raise ValueError('fixture writable')
        self.validated.append(path)
    def read(self,path,maximum):
        assert path in self.held and path in self.validated
        return path.read_bytes()[:maximum]
    def release(self,path):
        assert self.held[-1]==path
        self.held.pop();self.closed.append(path)


def fixture(tmp_path):
    root=tmp_path/'authority';root.mkdir();backend=Custody()
    policy=load_routing_policy({'policy_version':3});catalog=policy.as_dict()['catalog']
    catalog['generation']='fixture-authority-2'
    data=json.dumps(dict(schema='cochem-catalog-change-request/1',catalog=catalog,
        previous_policy_digest=policy.digest)).encode()
    digest=hashlib.sha256(data).hexdigest();(root/(digest+'.json')).write_bytes(data)
    pointer=dict(schema='cochem-catalog-authority-pointer/1',request_id='a'*32,proposal_sha256=digest)
    (root/'current-request.json').write_text(json.dumps(pointer),encoding='utf-8')
    return root,backend,policy,pointer


def test_custody_survives_use_and_releases_in_reverse_order(tmp_path):
    root,backend,policy,pointer=fixture(tmp_path)
    with _read_locked(root,policy,backend) as authority:
        assert authority.proposal_sha256==pointer['proposal_sha256']
        assert authority.change.previous_policy_digest==policy.digest
        assert root/'current-request.json' in backend.held
        assert root/(pointer['proposal_sha256']+'.json') in backend.held
        assert authority.change.as_dict()['activation_authorized'] is False
    assert not backend.held and backend.closed==list(reversed(backend.opened))


@pytest.mark.parametrize('stage',['acquire','inspect','validate'])
def test_partial_failures_close_every_acquired_handle(tmp_path,stage):
    root,backend,policy,_=fixture(tmp_path);backend.fail=(stage,'current-request.json')
    with pytest.raises(ValueError):
        with _read_locked(root,policy,backend):pytest.fail('bad authority accepted')
    assert not backend.held and backend.closed==list(reversed(backend.opened))


@pytest.mark.parametrize('fault',['traversal','duplicate','oversized','digest','extra_path'])
def test_invalid_authority_never_yields(tmp_path,fault):
    root,backend,policy,pointer=fixture(tmp_path)
    if fault=='traversal':pointer['proposal_sha256']='../outside'
    if fault=='digest':(root/(pointer['proposal_sha256']+'.json')).write_bytes(b'{}')
    if fault=='extra_path':pointer['path']='C:\\outside.json'
    data=json.dumps(pointer).encode()
    if fault=='duplicate':data=data[:-1]+b',"request_id":"bbbb"}'
    if fault=='oversized':data=b' '*4097
    (root/'current-request.json').write_bytes(data)
    with pytest.raises(ValueError):
        with _read_locked(root,policy,backend):pytest.fail('invalid authority accepted')
    assert not backend.held


def test_body_failure_releases_authority(tmp_path):
    root,backend,policy,_=fixture(tmp_path)
    with pytest.raises(RuntimeError):
        with _read_locked(root,policy,backend):raise RuntimeError('probe failed')
    assert not backend.held


def test_production_boundary_requires_system_before_opening_any_path(monkeypatch):
    from cochem_pipeline import windows
    def refuse():raise ValueError('not SYSTEM')
    monkeypatch.setattr(windows,'require_system',refuse)
    monkeypatch.setattr(windows,'_api',lambda:pytest.fail('native API must not load'))
    with pytest.raises(ValueError,match='not SYSTEM'):
        with protected_catalog_request(load_routing_policy({'policy_version':3})):pass


def test_windows_adapter_requests_noninheritable_reparse_safe_replacement_denials():
    from cochem_pipeline.catalog_authority import _WindowsCustody
    calls=[]
    def open_file(*args):calls.append(args);return 17
    win=SimpleNamespace(_api=lambda:{'kernel32':SimpleNamespace(CreateFileW=open_file)},WindowsIsolationError=ValueError)
    adapter=_WindowsCustody(win)
    assert adapter.acquire('fixture-directory',True)==17
    assert adapter.acquire('fixture-file',False)==17
    assert calls==[
        ('fixture-directory',0x20000,3,None,3,0x02200000,None),
        ('fixture-file',0x80000000,1,None,3,0x02200000,None)]


@pytest.mark.parametrize('mode,attributes,links,directory',[
    (stat.S_IFREG,0x400,1,False),(stat.S_IFLNK,0,1,False),
    (stat.S_IFREG,0,2,False),(stat.S_IFDIR,0,1,False),(stat.S_IFREG,0,1,True)])
def test_windows_metadata_rejects_reparse_links_and_wrong_object_types(mode,attributes,links,directory):
    from cochem_pipeline.catalog_authority import _WindowsCustody
    win=SimpleNamespace(_api=lambda:{},WindowsIsolationError=ValueError)
    path=SimpleNamespace(lstat=lambda:SimpleNamespace(st_mode=mode,st_file_attributes=attributes,st_nlink=links,st_size=1))
    with pytest.raises(ValueError):_WindowsCustody(win).inspect(path,directory)


def test_authority_root_is_428_and_missing_path_raises_file_not_found(monkeypatch):
    import ctypes
    from pathlib import Path
    from cochem_pipeline.catalog_authority import AUTHORITY_ROOT, _WindowsCustody

    assert AUTHORITY_ROOT == Path(r'C:\Program Files\CoChem\RoutingCatalog4.2.8')

    win = SimpleNamespace(
        _api=lambda: {'kernel32': SimpleNamespace(CreateFileW=lambda *a: ctypes.c_void_p(-1).value)},
        WindowsIsolationError=ValueError,
    )
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 2)
    with pytest.raises(FileNotFoundError):
        _WindowsCustody(win).acquire('missing-authority', True)
