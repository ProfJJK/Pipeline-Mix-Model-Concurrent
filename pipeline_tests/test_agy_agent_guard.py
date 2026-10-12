"""Temporary-file/ACL fixtures, not native Windows handle denial evidence."""
import hashlib
from pathlib import Path
import pytest
from cochem_pipeline.agy_agent_guard import RELATIVES, FULL, READ_DIRECTORY, READ_FILE, lock_verified_tree


def test_invocation_cannot_select_an_unguarded_agent(tmp_path):
    from cochem_pipeline.agy_agent_guard import require_agent_contract
    from supervisor_tests.test_runner import agy_spec
    spec = agy_spec()
    assert require_agent_contract(spec) == spec['agent_definition']
    arguments = spec['inference_only']['arguments']
    arguments[arguments.index('--agent') + 1] = 'default'
    with pytest.raises(ValueError, match='same reviewed'):
        require_agent_contract(spec)


def fixture(tmp_path):
    data = b'reviewed agent fixture\n'
    for relative in RELATIVES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    contract = dict(name='cochem-inference-only', sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data), relative_paths=list(RELATIVES))
    opened, closed = [], []
    def acquire(path, directory):
        opened.append((path, directory))
        return path
    def acl(path):
        flags = 0 if path.name == 'agent.md' else 3
        return 'S-1-5-18', True, [('S-1-5-18', FULL, flags), ('S-1-5-32-544', FULL, flags),
                                ('worker-sid', READ_FILE if flags == 0 else READ_DIRECTORY, flags)]
    return contract, opened, closed, dict(acquire=acquire, release=closed.append, acl=acl)


def test_every_discovery_ancestor_stays_held_until_explicit_cleanup(tmp_path):
    contract, opened, closed, backend = fixture(tmp_path)
    guard = lock_verified_tree(tmp_path, 'worker-sid', contract, **backend)
    assert not closed
    assert len(opened) == 9  # Profile, shared .gemini, config, two parents/leaves/files.
    for relative in RELATIVES:
        path = tmp_path / relative
        assert path in {item[0] for item in opened}
        assert all(parent in {item[0] for item in opened} for parent in path.parents if parent == tmp_path or tmp_path in parent.parents)
    guard.close()
    assert closed == [path for path, _ in reversed(opened)]
    guard.close()
    assert len(closed) == len(opened)


@pytest.mark.parametrize('teardown_ok', [True, False])
def test_native_wrapper_retains_guard_until_process_tree_cleanup(monkeypatch, teardown_ok):
    import threading
    from types import SimpleNamespace
    from cochem_pipeline import windows
    events = []
    process = windows.WindowsProcess.__new__(windows.WindowsProcess)
    process._lock = threading.RLock()
    process._process, process._job, process._token, process._profile, process._slot_lock = 1, 2, 3, 4, 5
    process._agent_guard = SimpleNamespace(close=lambda: events.append('guard_closed'))
    process.terminate = lambda: events.append('tree_terminated')
    process.wait = lambda timeout: events.append('parent_exited')
    def accounting(*args):
        events.append('tree_checked')
        if not teardown_ok:
            raise windows.WindowsIsolationError('fixture accounting failed')
        return True  # Zero-initialized accounting says no descendants.
    monkeypatch.setattr(windows, '_api', lambda: {
        'kernel32': SimpleNamespace(QueryInformationJobObject=accounting),
        'userenv': SimpleNamespace(UnloadUserProfile=lambda *a: events.append('profile_unloaded') or True)})
    monkeypatch.setattr(windows, '_close', lambda handle: events.append(('closed', handle)))
    if not teardown_ok:
        with pytest.raises(windows.WindowsCleanupError):
            process.close()
        assert 'guard_closed' not in events
        assert process._agent_guard is not None
    else:
        process.close()
        assert events.index('tree_checked') < events.index('guard_closed') < events.index('profile_unloaded')
        assert process._agent_guard is None


@pytest.mark.parametrize('fault', ['bytes', 'owner', 'writable', 'unprotected', 'missing', 'path_escape'])
def test_replacement_or_incomplete_staging_refuses_and_releases_handles(tmp_path, fault):
    contract, opened, closed, backend = fixture(tmp_path)
    if fault == 'bytes':
        (tmp_path / RELATIVES[1]).write_bytes(b'x' * contract['bytes'])
    elif fault == 'missing':
        (tmp_path / RELATIVES[1]).unlink()
    elif fault == 'path_escape':
        contract['relative_paths'][0] = '../agent.md'
    else:
        original = backend['acl']
        def bad_acl(path):
            owner, protected, rules = original(path)
            if fault == 'owner': owner = 'worker-sid'
            if fault == 'writable': rules[-1] = ('worker-sid', FULL, rules[-1][2])
            return owner, False if fault == 'unprotected' else protected, rules
        backend['acl'] = bad_acl
    with pytest.raises((ValueError, OSError)):
        lock_verified_tree(tmp_path, 'worker-sid', contract, **backend)
    assert closed == [path for path, _ in reversed(opened)]
