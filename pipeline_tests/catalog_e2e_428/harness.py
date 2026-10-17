"""Temporary installation, seeded board and the fixed host-adapter list.

The bootstrap is produced by the real r6 preparer from the pinned host inputs,
then relocated: every path moves under the test's temporary root and every
reviewed binary pin is rewritten to an emulated binary with the real version
string. Host adapters are replaced only where the real one would touch host
lifecycle, ACLs, accounts, Defender, ImDisk, Docker or the SYSTEM pipe ACL.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import importlib.util
from importlib.resources import files
import inspect
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
import uuid

from cochem_pipeline import windows
from pipeline_tests.catalog_e2e_428.emulators import NativeHost

REPO = Path(__file__).resolve().parents[2]
PREP = Path(r'C:\Users\ansac\CoChem427\r428-operational-prep-20261015-v1')
BUNDLE = Path(r'C:\Users\ansac\CoChem427\r428-bundle-3dab7f2')
HOST_INPUTS = (PREP / 'binary-bindings.json', PREP / 'candidate-profiles.json', BUNDLE / 'launch-manifest.json',
               BUNDLE / 'pipeline.json', BUNDLE / 'proposal.json', BUNDLE / 'pointer.json')
BASELINE_DIGEST = '6a76497a281e5ec23fca7f4a8d14a5581c5a35e71a94a0757ac95e7687e0e3c4'
ACTIVE_DIGEST = 'c8444fe2fd46b0f53edeaefc677ef7ff698c3e11cb83348a70255026a81da43d'
EXE_DIR = ('Program Files', 'CoChem', 'Native4.2.7-windows-20261006')
EXE_NAMES = {'codex': 'codex.exe', 'claude': 'claude.exe', 'gemini': 'agy.exe'}
BOOT_ID = 134051112000000000
VOLUME = {'volume_serial': 0x428E2E, 'device_number': 7, 'target': '\\Device\\ImDisk7', 'size_bytes': 8589934592,
          'backing': 'vm', 'nonpageable': False, 'filesystem': 'NTFS'}
HEALTHY = {'allowed_logical_processors': [0, 1, 2, 3], 'rss_mb': 40, 'cpu_percent': 1.0}
MODIFY = 0x1301BF
# 865a29b blobs (git show 865a29b:<path>), pinned by sha256 before compiling.
FROZEN = {'task_catalog_acceptance_428': '0be7d151776591f834e9d4e9e1ff1aaeed265db84bc4a7ba78b5937b3609df9d',
          'worker': 'eae10c431b56c727dd88e8508ee8d9ecb984b69741016adbafca89f194a487b2',
          'owner_task_catalog_428': '4938aac4de0357e9091a580671ba23d8f0cc3b2a92cbcec9ba1dc83be2dc8726',
          'native_effort': '58d6e857bd727a1f4c8cd413626255036724ca38c3563108c2cf0c1e373b1179'}
PATH_TEXT = re.compile(r'^[A-Za-z]:\\')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def host_inputs_present():
    return all(path.is_file() for path in HOST_INPUTS)


def load_preparer():
    spec = importlib.util.spec_from_file_location('operational_release_428_e2e',
                                                  REPO / 'scripts' / 'prepare_operational_release_428.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class HostInputs:
    """Real preparer outputs for the pinned r4 baseline (read-only host inputs)."""
    prepare: object
    policy: object
    baseline: object
    previous_raw: bytes
    r5_bootstrap: dict
    candidate: dict
    binary_bindings: dict
    catalog: dict
    profiles: list
    proposal: dict
    proposal_raw: bytes
    pointer_raw: bytes

    @classmethod
    def load(cls):
        from cochem_pipeline.routing import load_routing_policy
        prepare = load_preparer()
        previous_raw, _ = prepare.read_current_baseline()
        r5 = prepare.bootstrap_from_current_428(previous_raw, target_root=prepare.R6_TARGET_ROOT)
        policy, _ = prepare.active_routing_policy()
        bindings = json.loads((PREP / 'binary-bindings.json').read_bytes())
        catalog = json.loads((REPO / 'docs' / '4.2.8' / 'routing-candidate.json').read_bytes())
        candidate = prepare.route_active_policy(r5, policy, bindings, catalog)
        proposal_raw = (BUNDLE / 'proposal.json').read_bytes()
        return cls(prepare, policy, load_routing_policy(json.loads(previous_raw)['routing']), previous_raw, r5,
                   candidate, bindings, catalog, json.loads((PREP / 'candidate-profiles.json').read_bytes()),
                   json.loads(proposal_raw), proposal_raw, (BUNDLE / 'pointer.json').read_bytes())


def _walk(value, change):
    if isinstance(value, dict):
        return {key: _walk(item, change) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, change) for item in value]
    return change(value)


def strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def relocate(config, root, real_bindings, fake_bindings):
    """Every host path moves below root; every real binary pin becomes the fake pin."""
    pins = {real_bindings[name]['sha256']: fake_bindings[name]['sha256'] for name in real_bindings}
    exes = {real_bindings[name]['executable']: fake_bindings[name]['executable'] for name in real_bindings}
    result = _walk(deepcopy(config), lambda value: pins.get(value, exes.get(value, value)))
    private = root / 'ProgramData' / 'CoChemPipeline427' / 'private'
    corpus = root / 'Program Files' / 'CoChem' / 'Pipeline4.2.8-windows-20261017-r6' / 'source' / 'knowledge'
    result.update(private_root=str(private), token_file=str(root / 'CoChem427' / 'controller.token'),
                  git_executable=str(root / 'Program Files' / 'Git' / 'cmd' / 'git.exe'),
                  slot_roots={slot: str(root / 'ProgramData' / 'CoChemPipeline427' / 'workers' / slot)
                              for slot in result['slot_roots']})
    knowledge = result['knowledge']
    knowledge.update(source_root=str(corpus / '.sources'), wiki_root=str(corpus / 'wiki'),
                     manifest_path=str(corpus / 'v4.1.2_manifest.json'),
                     state_root=str(private / Path(knowledge['state_root']).name))
    result['ramdisk'].update(mount_root=str(root / 'ram'),
                             imdisk_executable=str(root / 'Windows' / 'System32' / 'imdisk.exe'))
    result['hardware']['cpu_temperature_probe'] = str(root / 'Program Files' / 'CoChem' / 'CpuSensors' / 'cochem-cpu-temperature.exe')
    docker = result['docker']
    docker.update(enabled=False, executable=str(root / 'Program Files' / 'Docker' / 'docker.exe'),
                  pipe_server_executables=[str(root / 'Program Files' / 'Docker' / 'com.docker.backend.exe')])
    result.pop('coding_projects', None)
    result.pop('coding_registration', None)
    return result


def write_corpus(root):
    """The installed SRS and owner amendment, registered as the knowledge authority requires."""
    from cochem_pipeline.planning_governance import canonical_authority
    root.mkdir(parents=True)
    installed = files('cochem_pipeline').joinpath('specification')
    documents = {'.sources/4.2.7_SRS.md': installed.joinpath('4.2.7_SRS.md').read_bytes(),
                 '.sources/SRS_ADDENDUM_4.2.7.md': installed.joinpath('SRS_ADDENDUM_4.2.7.md').read_bytes(),
                 'wiki/00_skeleton.md': b'# Canonical\n[SRS](../.sources/4.2.7_SRS.md)\n'
                                        b'[Decisions](../.sources/SRS_ADDENDUM_4.2.7.md)\n'}
    revision = canonical_authority()['specification_revision']
    entries = []
    for name, raw in documents.items():
        target = root / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(raw)
        entries.append({'path': name, 'sha256': sha(raw), 'authority_revision': revision,
                        'authority': 'current_normative' if name.endswith('4.2.7_SRS.md') else
                        'owner_decision' if 'ADDENDUM' in name else 'unclassified'})
    (root / 'v4.1.2_manifest.json').write_text(json.dumps({'manifest_version': '4.2.7', 'documents': entries,
                                                          'srs_documents': ['wiki/00_skeleton.md']}))


def seed_board(job_db, host):
    """Baseline 6a76 installed, then r4's own c8444 generation published; no task catalog."""
    from cochem_pipeline import catalog_journal
    from cochem_pipeline.catalog_activation import compile_change
    from cochem_pipeline.catalog_authority import CatalogAuthority
    from cochem_pipeline.store import JobStore
    store = JobStore(job_db, routing_policy=host.baseline)
    with store._connection() as conn:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        catalog_journal.initialize(conn, host.baseline)
        conn.commit()
    store.close()
    plan = compile_change(host.baseline, host.proposal['catalog'], expected_policy_digest=BASELINE_DIGEST)
    pointer = json.loads(host.pointer_raw)
    assert plan.policy.digest == ACTIVE_DIGEST and pointer['proposal_sha256'] == sha(host.proposal_raw)
    authority = CatalogAuthority(pointer['request_id'], sha(host.pointer_raw), pointer['proposal_sha256'], plan)
    proof = [dict(zip(('provider', 'model', 'reasoning_effort'), plan.control_target), status='NATIVE_SELECTOR_ACCEPTED',
                  cleanup_verified=True, plan_digest=plan.digest, request_id=authority.request_id,
                  reservation_id='r4-control-probe-20261014', fencing_token=1)]
    conn = sqlite3.connect(job_db, isolation_level=None)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        catalog_journal.publish(conn, authority, proof)
        conn.commit()
    finally:
        conn.close()


class Violation(AssertionError):
    """A guarded host adapter was reached; recorded even if production code catches it."""


@dataclass
class Recorder:
    root: Path
    worker_roots: dict = field(default_factory=dict)
    code_paths: list = field(default_factory=list)
    acl_paths: list = field(default_factory=list)
    acl_writes: list = field(default_factory=list)
    docker: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    layouts: list = field(default_factory=list)

    def under(self, path):
        return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(str(self.root)) + os.sep)

    def fail(self, name):
        def guarded(*args, **kwargs):
            self.violations.append(name)
            raise Violation(f'Host adapter {name} is forbidden in the offline end-to-end test')
        return guarded

    def code_path(self, path):
        resolved = Path(path).resolve(strict=True)
        allowed = (self.under(resolved) or resolved == Path(sys.executable).resolve()
                   or (REPO / 'src') in resolved.parents)
        self.code_paths.append(str(resolved))
        if not allowed:
            self.violations.append('validate_code_path:' + str(resolved))
            raise windows.WindowsIsolationError('Offline e2e: code path outside the temporary installation')

    def acl(self, path):
        """Identity-only ACL fixture: SYSTEM/BA-protected, worker MODIFY on its RAM slot."""
        absolute = os.path.normcase(os.path.abspath(path))
        if not self.under(absolute):
            self.violations.append('_acl:' + absolute)
            raise Violation('Offline e2e: ACL read outside the temporary installation')
        self.acl_paths.append(absolute)
        for slot_root, sid in self.worker_roots.items():
            if absolute == slot_root or absolute.startswith(slot_root + os.sep):
                return windows.SYSTEM_SID, True, [(windows.SYSTEM_SID, windows.FULL_CONTROL, 3), (sid, MODIFY, 3)]
        return windows.SYSTEM_SID, True, [(windows.SYSTEM_SID, windows.FULL_CONTROL, 3),
                                          (windows.ADMIN_SID, windows.FULL_CONTROL, 3)]

    def set_acl(self, path, sid):
        # Only RamWorkspace.bind_native_caches reaches this (the profile's
        # .claude/projects before the junction); the real setter is never called.
        if not self.under(path) or Path(path).name != 'projects':
            self.violations.append('_set_acl:' + str(path))
            raise Violation('Offline e2e: ACL write outside the emulated profile cache')
        self.acl_writes.append((str(path), sid))

    def docker_boundary(self, endpoint, identities, *, required=True, trusted_operator=None,
                        trusted_server_executables=()):
        if required is not False or len(identities) != 1:
            self.violations.append('docker_boundary_required')
            raise Violation('Offline e2e: Docker is disabled in the relocated bootstrap')
        self.docker.append((endpoint, tuple(identity.name for identity in identities.values())))
        return {}


def owner_only_pipe():
    """transport._windows_pipe with an owner-only DACL instead of SYSTEM-only.

    A non-SYSTEM test process cannot open its own client end of a SY-only pipe.
    The production bytes are asserted unchanged before this copy is compiled.
    """
    from cochem_pipeline import transport
    source = inspect.getsource(transport._windows_pipe)
    assert source.count("'D:P(A;;GA;;;SY)'") == 1 and source.count('    require_system()\n') == 1
    patched = source.replace('    require_system()\n', '', 1).replace("'D:P(A;;GA;;;SY)'", "'D:P(A;;GA;;;OW)'", 1)
    namespace = dict(vars(transport))
    exec(compile(patched, '<offline-e2e transport._windows_pipe owner-only DACL>', 'exec'), namespace)
    return namespace['_windows_pipe']


class StubGuard:
    """Explicit admission stimulus: no CPU-temperature probe, GPU or disk counters."""
    def __init__(self, *, max_agents, workspace, policy, workspaces):
        self.max_agents, self.workspaces = max_agents, [str(path) for path in workspaces]

    def evaluate(self):
        return {'capacity': self.max_agents, 'state': 'normal', 'action': 'none', 'reasons': []}

    def capacity(self):
        return self.max_agents

    def latest_snapshot(self):
        return {'source': 'offline-e2e-stub', 'capacity': self.max_agents}

    snapshot = latest_snapshot


def fake_ensure(recorder):
    def ensure(self):
        from cochem_pipeline import ramdisk
        windows.require_system()
        if not self.config.enabled or not recorder.under(self.config.workspace_root):
            raise Violation('Offline e2e: RAM workspace outside the temporary installation')
        boundary = self.config.workspace_root
        boundary.mkdir(parents=True, exist_ok=True)
        ramdisk._no_content_index(boundary, apply=True)
        for slot, identity in self.identities.items():
            root = boundary / slot
            root.mkdir(exist_ok=True)
            ramdisk._no_content_index(root, apply=True)
            self.workspaces[slot] = ramdisk.RamWorkspace(self.config, slot, identity.name, VOLUME['volume_serial'],
                                                         VOLUME['device_number'], self.private_root)
        return {'schema': 1, 'state': 'READY', 'source': 'offline-e2e', 'slots': sorted(self.workspaces)}
    return ensure


def install_guards(monkeypatch, env):
    """The fixed host-adapter list. Everything else in the phase is production code."""
    import subprocess
    from cochem_pipeline import (agy_tool_registry, catalog_runtime, containers, controller_guard, deployment,
                                 ramdisk, resource_limits, runtime as runtime_module, transport)
    recorder = env.recorder
    monkeypatch.delenv('COCHEM_WARDEN_CONTAINMENT_ID', raising=False)
    monkeypatch.setattr(subprocess, 'Popen', recorder.fail('subprocess.Popen'))
    monkeypatch.setattr(windows, 'require_system', lambda: None)
    monkeypatch.setattr(windows, 'validate_code_path', recorder.code_path)
    monkeypatch.setattr(windows, '_acl', recorder.acl)
    monkeypatch.setattr(windows, '_account_sid', lambda name: 'S-1-5-21-428-e2e-' + name)
    monkeypatch.setattr(windows, '_sid_text', lambda sid: sid)
    monkeypatch.setattr(windows, '_set_acl', recorder.set_acl)
    monkeypatch.setattr(windows, 'current_boot_identity', lambda: BOOT_ID)
    monkeypatch.setattr(windows, 'validate_layout', lambda *args, **kwargs: recorder.layouts.append(args[0]) or
                        {'system': True, 'source': 'offline-e2e-stub'})
    for name in ('_powershell', '_enable_system_privileges', '_worker_token', 'login_worker', '_protect_boundary',
                 'provision_layout', 'protect_controller_token', 'defender_exclusions', '_grant_batch_logon',
                 '_provision_identity', '_create_operator_file'):
        monkeypatch.setattr(windows, name, recorder.fail('windows.' + name))
    monkeypatch.setattr(windows, 'launch_worker', env.native.launch_worker)
    monkeypatch.setattr(resource_limits, 'controller_limits',
                        lambda limits, apply: {'source': 'offline-e2e-stub', 'apply_requested': apply})
    monkeypatch.setattr(runtime_module, 'HardwareGuard', StubGuard)
    monkeypatch.setattr(controller_guard.ControllerMonitor, 'from_policy', classmethod(
        lambda cls, policy=None, **kwargs: cls(getattr(policy, 'recovery_seconds', 10.0),
                                              getattr(policy, 'recovery_samples', 3), measure=lambda: dict(HEALTHY))))
    monkeypatch.setattr(ramdisk.RamdiskConfig, 'adopted_drive', property(lambda self: True))
    monkeypatch.setattr(ramdisk.RamdiskManager, 'ensure', fake_ensure(recorder))
    monkeypatch.setattr(ramdisk, '_native_volume', lambda config: dict(VOLUME))
    monkeypatch.setattr(ramdisk, '_validate_adopted_parent',
                        lambda mount: None if recorder.under(mount) else recorder.fail('adopted_parent')())
    for name in ('_mount_target', '_create_adopted_boundary', '_remove_stale_mount'):
        monkeypatch.setattr(ramdisk, name, recorder.fail('ramdisk.' + name))
    monkeypatch.setattr(deployment, 'verify_docker_access_boundary', recorder.docker_boundary)
    for name in ('attest_docker_pipe_server', 'verify_worker_docker_denial'):
        monkeypatch.setattr(deployment, name, recorder.fail('deployment.' + name))
    monkeypatch.setattr(containers.DockerRunner, '__init__', recorder.fail('DockerRunner'))
    monkeypatch.setattr(catalog_runtime.CatalogController, 'step', recorder.fail('CatalogController.step'))
    if not (os.environ.get('COCHEM_SYSTEM_TESTS') == '1' and _is_system()):
        monkeypatch.setattr(transport, '_windows_pipe', owner_only_pipe())
    # The reviewed 1.3.1 registry exception stays active for the emulated binary.
    monkeypatch.setattr(agy_tool_registry, 'BINARY_SHA256', env.fake_bindings['gemini']['sha256'])
    return recorder


def _is_system():
    try:
        windows.require_system()
        return True
    except Exception:
        return False


class Clock:
    """Simulated wall/monotonic skew for lease and hold expiry; never sleeps."""
    def __init__(self, monkeypatch, *, monotonic=False):
        self.skew = 0.0
        real_time, real_monotonic = time.time, time.monotonic
        monkeypatch.setattr(time, 'time', lambda: real_time() + self.skew)
        if monotonic:
            monkeypatch.setattr(time, 'monotonic', lambda: real_monotonic() + self.skew)


@dataclass
class Environment:
    root: Path
    host: HostInputs
    profiles: list
    bootstrap: dict
    fake_bindings: dict
    request: dict
    bootstrap_path: Path
    request_path: Path
    native: NativeHost
    recorder: Recorder
    runtimes: list = field(default_factory=list)

    @classmethod
    def build(cls, root, host, profiles, *, bootstrap='active', request_id=None):
        from cochem_pipeline.task_catalog_acceptance_428 import encoded, execution_bindings, prepare_request
        root = Path(root)
        fakes = {}
        for name, binding in host.binary_bindings.items():
            path = root.joinpath(*EXE_DIR, EXE_NAMES[name])
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = b'MZ\x90\x00offline CoChem 4.2.8 e2e emulated native CLI: ' + name.encode() + b'\n' + bytes(4096)
            path.write_bytes(payload)
            fakes[name] = dict(executable=str(path), sha256=sha(payload), version=binding['version'])
        # active: real r6 route_active_policy output; baseline: the r5-style
        # bootstrap still routing 6a76 (bootstrap_from_current_428 alone).
        source = host.r5_bootstrap if bootstrap == 'baseline' else host.candidate
        config = relocate(source, root, host.binary_bindings, fakes)
        if bootstrap == 'retired_binding':
            original = relocate(host.r5_bootstrap, root, host.binary_bindings, fakes)['providers']['gemini']
            gemini = config['providers']['gemini']
            gemini['model_bindings']['gemini-3.1-pro:high'] = original['model_bindings']['gemini-3.1-pro:high']
            gemini['effort_contracts']['gemini-3.1-pro:high'] = original['effort_contracts']['gemini-3.1-pro:high']
        elif bootstrap == 'no_codex_contracts':
            config['providers']['codex'].pop('effort_contracts')
        texts = list(strings(config))
        assert not any(value in texts for binding in host.binary_bindings.values()
                       for value in (binding['sha256'], binding['executable']))
        recorder = Recorder(root)
        outside = [value for value in texts if PATH_TEXT.match(value) and not recorder.under(value)]
        assert not outside, outside
        private = Path(config['private_root'])
        private.mkdir(parents=True)
        for slot_root in config['slot_roots'].values():
            Path(slot_root).mkdir(parents=True)
        token = Path(config['token_file'])
        token.parent.mkdir(parents=True)
        token.write_text('offline-e2e-controller-token-' + uuid.uuid4().hex, encoding='utf-8')
        write_corpus(Path(config['knowledge']['source_root']).parent)
        Path(config['ramdisk']['mount_root']).mkdir(parents=True)
        workspace_root = Path(config['ramdisk']['mount_root']) / config['ramdisk']['workspace_subdirectory']
        recorder.worker_roots = {os.path.normcase(os.path.abspath(workspace_root / slot)):
                                 'S-1-5-21-428-e2e-' + spec['name'] for slot, spec in config['workers'].items()}
        seed_board(private / 'job_board.db', host)
        inputs = root / 'inputs'
        inputs.mkdir()
        bootstrap_path = inputs / 'pipeline.json'
        bootstrap_path.write_bytes(json.dumps(config, indent=2).encode('utf-8'))
        request = prepare_request(host.policy, host.catalog, fakes, request_id=request_id or uuid.uuid4().hex,
                                  execution_bindings=execution_bindings(config['providers'], config['workers']),
                                  candidate_profile_ids=profiles, allow_partial_publication=True)
        request_path = inputs / 'task-catalog-request.json'
        request_path.write_bytes(encoded(request))
        native = NativeHost(executables={name: spec['executable'] for name, spec in fakes.items()},
                            versions={name: spec['version'] for name, spec in fakes.items()},
                            profiles_root=root / 'Users')
        return cls(root, host, profiles, config, fakes, request, bootstrap_path, request_path, native, recorder)

    @property
    def private(self):
        return Path(self.bootstrap['private_root'])

    @property
    def job_db(self):
        return self.private / 'job_board.db'

    @property
    def workspace_root(self):
        return Path(self.bootstrap['ramdisk']['mount_root']) / self.bootstrap['ramdisk']['workspace_subdirectory']

    def capture_runtimes(self, monkeypatch):
        from cochem_pipeline.runtime import Runtime
        original = Runtime.__init__
        def construct(runtime, config):
            self.runtimes.append(runtime)
            original(runtime, config)
        monkeypatch.setattr(Runtime, '__init__', construct)

    def run_phase(self, name='phase-output', **kwargs):
        from cochem_pipeline import owner_task_catalog_428 as owner
        output = self.root / name
        output.mkdir()
        options = dict(timeout_seconds=300, poll_seconds=.05)
        options.update(kwargs)
        return owner.run_owner_phase(self.bootstrap_path, sha(self.bootstrap_path.read_bytes()), self.request_path,
                                     sha(self.request_path.read_bytes()), output, **options), output

    def query(self, sql, args=()):
        conn = sqlite3.connect(self.job_db.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def table(self, name):
        return bool(self.query("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))

    def probe_rows(self):
        if not self.table('pipeline_catalog_probes'):
            return []
        names = ('reservation_id', 'request_id', 'target_json', 'worker_slot', 'containment_id', 'boot_id',
                 'lease_expires_at', 'reserved_at', 'cleanup_at', 'result_json', 'consumed_at', 'sequence')
        return [dict(zip(names, row)) for row in self.query('SELECT ' + ','.join(names) +
                                                            ' FROM pipeline_catalog_probes ORDER BY sequence')]

    def evidence(self):
        if not self.table('pipeline_task_probe_evidence'):
            return []
        return [json.loads(row[0]) for row in self.query('SELECT evidence_json FROM pipeline_task_probe_evidence')]

    def holds(self):
        if not self.table('pipeline_task_catalog_holds'):
            return []
        return [json.loads(row[0]) for row in self.query('SELECT evidence_json FROM pipeline_task_catalog_holds')]

    def active_catalog(self):
        from cochem_pipeline import catalog_journal
        conn = sqlite3.connect(self.job_db.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            return catalog_journal.active_policy(conn).digest, catalog_journal.active_task_catalog(conn)
        finally:
            conn.close()

    def occupancy(self):
        return sum(row['cleanup_at'] is None for row in self.probe_rows())

    def ram_slots_empty(self):
        return {slot.name: not any(slot.iterdir()) for slot in self.workspace_root.iterdir()}

    def targets(self):
        from cochem_pipeline.task_catalog_acceptance_428 import decode_request
        data = self.request_path.read_bytes()
        decoded = decode_request(data, self.host.policy, None, expected_sha256=sha(data))
        return sorted(set(decoded.plan.required_targets) | {decoded.plan.control_target})


def native_groups(launches):
    """Split the sequential launch log into per-probe native sequences."""
    groups, current = [], []
    for row in launches:
        current.append(row)
        if row['kind'] == 'inference':
            groups.append(current)
            current = []
    return groups, current


class FrozenSource:
    """865a29b definitions compiled at test time from git, each blob sha256-pinned."""
    def __init__(self, blobs):
        self.blobs = blobs

    @classmethod
    def load(cls, runner):
        blobs = {}
        for name, pin in FROZEN.items():
            data = runner(['git', '-C', str(REPO), 'show', f'865a29b:src/cochem_pipeline/{name}.py'])
            if sha(data) != pin:
                raise AssertionError(f'865a29b {name}.py blob differs from its pin')
            blobs[name] = data
        return cls(blobs)

    def function(self, module, qualified):
        """Compile one frozen function into a copy of the live module namespace."""
        tree = ast.parse(self.blobs[module.__name__.rsplit('.', 1)[-1]])
        owner, _, name = qualified.rpartition('.')
        scope = tree.body
        if owner:
            scope = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner).body
        node = next(item for item in scope if isinstance(item, ast.FunctionDef) and item.name == name)
        namespace = dict(vars(module))
        exec(compile(ast.Module(body=[node], type_ignores=[]), f'865a29b:src/cochem_pipeline/'
                     f'{module.__name__.rsplit(".", 1)[-1]}.py', 'exec'), namespace)
        return namespace[name]


def live_threads(*prefixes):
    return [thread.name for thread in threading.enumerate() if thread.name.startswith(prefixes) and thread.is_alive()]


def wait_threads(*prefixes, seconds=10):
    deadline = time.monotonic() + seconds
    while live_threads(*prefixes) and time.monotonic() < deadline:
        time.sleep(.05)
    return live_threads(*prefixes)


def receipt(env, reservation_id):
    return json.loads((env.private / 'attempts' / reservation_id / 'receipt.json').read_text(encoding='utf-8'))


__all__ = ['ACTIVE_DIGEST', 'BASELINE_DIGEST', 'BOOT_ID', 'Clock', 'Environment', 'FrozenSource', 'HostInputs',
           'host_inputs_present', 'install_guards', 'live_threads', 'native_groups', 'receipt', 'sha', 'wait_threads']
