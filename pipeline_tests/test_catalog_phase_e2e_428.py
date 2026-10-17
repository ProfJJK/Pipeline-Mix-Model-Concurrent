"""Offline end-to-end owner catalog phase on the REAL Runtime (no host side effects).

run_owner_phase runs with the real Runtime, JobStore/SQLite board, knowledge
index, run_acceptance, NativeRunner (preflight, auth, effort contracts,
provider_command, receipts), record_result/publish/enabled_candidate and
load_config. Only windows.launch_worker (pipeline_tests/catalog_e2e_428/
emulators.py) and the fixed host-adapter list in harness.install_guards are
replaced. The bootstrap comes from the real r6 preparer on the pinned r4 bundle,
relocated into the temporary directory with emulated binaries. 865a29b
negatives compile frozen functions from git at test time, each blob pinned.
Source tests are not native acceptance, deployment or host evidence.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

import pytest

from cochem_pipeline import catalog_runtime
from cochem_pipeline.task_routing import digest
from pipeline_tests.catalog_e2e_428.harness import (
    ACTIVE_DIGEST, BASELINE_DIGEST, BOOT_ID, Clock, Environment, FrozenSource, HostInputs, host_inputs_present,
    install_guards, live_threads, native_groups, receipt, sha, wait_threads)

pytestmark = pytest.mark.skipif(not host_inputs_present(),
                                reason='pinned r4 bundle and r6 operational preparation inputs are host inputs')
SMALL = ['haiku-med', 'sonnet-med', 'luna-low']  # claude haiku/sonnet medium, codex luna low, gemini control
READY, HELD = 'TASK_CATALOG_CANDIDATE_READY', 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
SEQUENCES = {'codex': ['version', 'mcp', 'mcp', 'features', 'auth', 'inference'],
             'claude': ['version', 'help', 'auth', 'inference'], 'gemini': ['version', 'version', 'auth', 'inference']}
PROBE_KINDS = {'codex': ['verify_reviewed_effort_version', 'enumerate_mcp', 'verify_disabled_mcp',
                         'verify_disabled_host_features'],
               'claude': ['verify_reviewed_effort_version', 'verify_inference_only_flags'],
               'gemini': ['verify_reviewed_effort_version', 'verify_reviewed_native_version']}
THREADS = ('task-catalog-guard', 'native-stdin', 'e2e-native-', 'docker-maintenance')
REAL_CATALOG_STEP = catalog_runtime.CatalogController.step


@pytest.fixture(scope='module')
def host():
    return HostInputs.load()


@pytest.fixture(scope='module')
def frozen():
    import subprocess  # Read-only git blobs, fetched before any per-test Popen guard.
    return FrozenSource.load(lambda argv: subprocess.run(argv, capture_output=True, check=True, timeout=60).stdout)


@pytest.fixture
def make_env(host, tmp_path, monkeypatch):
    def build(profiles=SMALL, **kwargs):
        env = Environment.build(tmp_path / 'h', host, profiles, **kwargs)
        install_guards(monkeypatch, env)
        env.capture_runtimes(monkeypatch)
        return env
    return build


def restore_authority(result):
    """Test-OpRestoreAuthority plus Restore-OpPrevious's catalog identity check."""
    proof = result.get('publication_proof') or {}
    return (result.get('publication_state') == 'NOT_COMMITTED' and result.get('runtime_resources_closed') is True
            and proof.get('catalog_probe_cleanup_verified') is True
            and proof.get('active_policy_sha256') == ACTIVE_DIGEST and 'active_catalog_sha256' in proof)


def hermetic(env):
    """No guarded adapter was reached (even if production code caught it)."""
    assert env.recorder.violations == [] and env.native.errors == []
    assert wait_threads(*THREADS) == []
    assert env.recorder.code_paths and all(env.recorder.under(path) for path, _ in env.recorder.acl_writes)


def held(result, output, phase, error_type):
    assert result['status'] == HELD and result['phase'] == phase, result
    assert result['error_type'] == error_type and result['cutover_requested'] is False
    assert (output / 'held.json').is_file() and not (output / 'result.json').exists()
    assert json.loads((output / 'held.json').read_bytes()) == result


def target_of(row):
    return tuple(json.loads(row['target_json']))


# --- 1. Positive full run (27 profiles, 28 targets), replay, candidate runtime ---------

@pytest.fixture(scope='module')
def full_run(host, tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        env = Environment.build(tmp_path_factory.mktemp('e2e-full'), host, host.profiles)
        install_guards(patch, env)
        env.capture_runtimes(patch)
        containment_env = os.environ.get('COCHEM_WARDEN_CONTAINMENT_ID')
        started = time.monotonic()
        result, output = env.run_phase()
        seconds = time.monotonic() - started
        first = dict(launches=list(env.native.launches), rows=env.probe_rows(), evidence=env.evidence(),
                     board=env.active_catalog(), ram=env.ram_slots_empty(), threads=wait_threads(*THREADS),
                     docker=list(env.recorder.docker), cache_acl=list(env.recorder.acl_writes),
                     code_paths=list(env.recorder.code_paths), layouts=list(env.recorder.layouts))
        replay, replay_output = env.run_phase('replay-output')
        return dict(env=env, result=result, output=output, seconds=seconds, first=first, replay=replay,
                    replay_output=replay_output, containment_env=containment_env)


def test_full_run_publishes_with_real_runtime_seats_and_board(full_run):
    env, result, output, first = full_run['env'], full_run['result'], full_run['output'], full_run['first']
    assert result['status'] == READY, result
    assert result['cleanup_verified'] is True and result['runtime_resources_closed'] is True
    assert result['runtime_constructed'] is True and result['catalog_published'] is True
    assert result['publication_state'] == 'COMMITTED'
    assert result['publication_proof']['catalog_probe_cleanup_verified'] is True
    assert json.loads((output / 'result.json').read_bytes()) == result and not (output / 'held.json').exists()
    assert any(row['status'] == 'AVAILABLE' for row in result['coverage'])
    # N6: the one-shot phase is not Warden-launched; seats use the catalog identity.
    assert full_run['containment_env'] is None
    runtime = env.runtimes[0]
    assert runtime.containment_id is None and re.fullmatch('[0-9a-f]{32}', runtime.catalog.containment_id)
    assert runtime.quarantined == {} and runtime.last_capacity == 4 and runtime.boot_id == BOOT_ID
    # The real constructor and guard ticks ran: knowledge index, controller
    # monitor, layout/code-path checks and the per-launch Docker boundary.
    assert runtime.components['knowledge']['state'] == 'healthy'
    assert runtime.components['warden_controller']['admission_ready'] is True
    assert first['layouts'] == [env.private] and str(Path(sys.executable).resolve()) in first['code_paths']
    assert len(first['launches']) == 15 * 6 + 10 * 4 + 3 * 4 == len(first['docker'])
    assert {endpoint for endpoint, _ in first['docker']} == {env.bootstrap['docker']['endpoint']}
    assert all(row['cache_bound'] for row in first['launches']) and first['cache_acl']
    for profile in (env.root / 'Users').iterdir():  # Real FSCTL junction into the worker's RAM slot.
        assert (profile / '.claude' / 'projects').lstat().st_file_attributes & 0x400
    targets = env.targets()
    assert len(targets) == 28 and [t[0] for t in targets].count('claude') == 10
    assert [t[0] for t in targets].count('codex') == 15 and [t[0] for t in targets].count('gemini') == 3
    rows = first['rows']
    assert [target_of(row) for row in rows] == targets
    for row in rows:
        assert row['containment_id'] == runtime.catalog.containment_id and row['boot_id'] == runtime.boot_id
        assert row['cleanup_at'] is not None and row['consumed_at'] is not None
        assert abs(row['lease_expires_at'] - row['reserved_at'] - 600) < 1
        assert json.loads(row['result_json'])['status'] == 'NATIVE_SELECTOR_ACCEPTED'
    evidence = first['evidence']
    assert len(evidence) == 28 and {row['status'] for row in evidence} == {'NATIVE_SELECTOR_ACCEPTED'}
    assert all(row['binary_sha256'] == env.fake_bindings[row['provider']]['sha256'] for row in evidence)
    policy, catalog = first['board']
    request_sha = sha(env.request_path.read_bytes())
    assert policy == ACTIVE_DIGEST and catalog['request_id'] == env.request['request_id']
    assert catalog['proposal_sha256'] == request_sha and catalog['plan_digest'] == env.request['plan_digest']
    assert all(first['ram'].values()) and len(first['ram']) == 6
    assert first['threads'] == []
    hermetic(env)


def test_full_run_receipts_bind_effort_binary_version_and_prompt_for_all_providers(full_run):
    env, first = full_run['env'], full_run['first']
    evidence = {row['reservation_id']: row for row in first['evidence']}
    groups, rest = native_groups(first['launches'])
    assert rest == [] and len(groups) == 28
    for row, group in zip(first['rows'], groups):
        provider, model, effort = target_of(row)
        binding = env.fake_bindings[provider]
        assert [launch['kind'] for launch in group] == SEQUENCES[provider]
        assert {launch['slot'] for launch in group} == {row['worker_slot']}
        inference = group[-1]
        assert (inference['model'], inference['efforts']) == (
            (model, [effort]) if provider != 'gemini' else (f'{model}-{effort}', []))
        document = receipt(env, row['reservation_id'])
        assert digest(document) == evidence[row['reservation_id']]['receipt_sha256']
        assert document['provider'] == provider and document['requested_model'] == model
        assert document['requested_effort'] == effort and document['worker_slot'] == row['worker_slot']
        assert document['worker_account'] == env.bootstrap['workers'][row['worker_slot']]['name']
        assert document['route_reservation_id'] == row['reservation_id']
        assert document['fencing_token'] == row['sequence'] and document['attempt_id'] == row['reservation_id']
        assert document['prompt_sha256'] == inference['stdin_sha256'] and document['pid'] == inference['pid']
        assert document['prompt_bytes'] == inference['stdin_bytes'] > 0  # Delivered through the named pipe.
        assert document['execution_kind'] == 'native_cli' and document['subscription_verified'] is True
        policy = document['inference_policy']
        chosen = policy['reasoning_effort']
        assert (chosen['requested_profile'], chosen['model']) == (effort, model)
        assert (chosen['executable_sha256'], chosen['version']) == (binding['sha256'], binding['version'])
        assert [probe['probe'] for probe in policy['probes']] == PROBE_KINDS[provider]
        version = policy['probes'][0]
        assert version['stdout_sha256'] == hashlib.sha256((binding['version'] + '\n').encode()).hexdigest()
        if provider == 'codex':
            assert version['stdout_sha256'] == hashlib.sha256(b'codex-cli 0.160.0\n').hexdigest()
            assert policy['workspace_selection'] == 'validated_process_cwd' and policy['sandbox'] == 'read-only'
            assert all(launch['efforts'] == [effort] for launch in group[1:])
            assert chosen['observation_status'] == 'not_reported_by_reviewed_cli'
        if provider == 'claude':
            assert document['reported_model'] == model and document['ramdisk_cache']['enabled'] is True
            assert document['ramdisk_cache']['native_report_verified'] is True
        if provider == 'gemini':
            assert document['native_reported_model'] == f'{model}-{effort}'
            assert policy['tool_registry']['advertised_count'] == 60


def test_full_run_candidate_configuration_loads_routes_active_policy_and_bindings(full_run, monkeypatch):
    from cochem_pipeline.config import load_config
    from cochem_pipeline.task_catalog_acceptance_428 import execution_bindings
    env, result, output = full_run['env'], full_run['result'], full_run['output']
    install_guards(monkeypatch, env)
    candidate = json.loads((output / 'pipeline.json').read_bytes())
    accepted = json.loads((output / 'accepted-catalog.json').read_bytes())
    assert sha((output / 'pipeline.json').read_bytes()) == result['configuration_sha256']
    assert sha((output / 'accepted-catalog.json').read_bytes()) == result['catalog_sha256']
    loaded = load_config(str(output / 'pipeline.json'))
    assert loaded.routing.digest == ACTIVE_DIGEST and loaded.catalog_activation is True
    assert loaded.task_planning.catalog_file == output / 'accepted-catalog.json'
    assert loaded.task_planning.read_catalog() == accepted and accepted['host_accepted'] is True
    assert execution_bindings(candidate['providers'], candidate['workers']) == env.request['execution_bindings']
    assert {key: value for key, value in candidate.items() if key not in ('task_planning',)} == {
        key: value for key, value in env.bootstrap.items() if key not in ('task_planning',)}
    hermetic(env)


def test_full_run_replay_into_fresh_root_needs_no_native_launch(full_run):
    env, replay, first = full_run['env'], full_run['replay'], full_run['first']
    assert replay['status'] == READY and replay['publication_state'] == 'COMMITTED', replay
    assert replay['catalog_sha256'] == full_run['result']['catalog_sha256']
    assert len(env.native.launches) == len(first['launches'])
    assert len(env.evidence()) == 28 and len(env.runtimes) == 2
    assert (full_run['replay_output'] / 'accepted-catalog.json').read_bytes() == (
        full_run['output'] / 'accepted-catalog.json').read_bytes()


def test_full_run_candidate_runtime_reports_enabled_connected_planning(full_run, monkeypatch):
    """Mirrors Wait-OpHealth $root $true: the produced candidate boots the real Runtime."""
    from contextlib import contextmanager
    from cochem_pipeline.config import load_config
    from cochem_pipeline.runtime import Runtime
    from cochem_pipeline.service import redact
    env, output = full_run['env'], full_run['output']
    install_guards(monkeypatch, env)
    # The service tick polls the protected catalog pointer; offline it is absent,
    # exactly as on a host with no pending catalog change request.
    monkeypatch.setattr(catalog_runtime.CatalogController, 'step', REAL_CATALOG_STEP)
    @contextmanager
    def no_pointer(policy, resolver=None):
        raise FileNotFoundError('offline: no protected catalog pointer')
        yield
    runtime = Runtime(load_config(str(output / 'pipeline.json')))
    try:
        runtime.catalog.reader = no_pointer
        runtime.tick()
        runtime.tick()
        health = redact(runtime.status())
        accepted = json.loads((output / 'accepted-catalog.json').read_bytes())
        assert health['version'] == '4.2.8' and health['service_identity'] == 'SYSTEM'
        assert health['task_planning']['status'] == 'ENABLED', health['task_planning']
        assert health['task_planning']['execution_materialization'] == 'CONNECTED', health['task_planning']
        assert health['admission_capacity'] >= 1 and runtime.last_capacity == 4
        assert health['components']['warden_controller']['admission_ready'] is True
        assert health['components']['knowledge']['state'] == 'healthy'
        assert health['catalog_activation']['status'] == 'IDLE' and health['quarantined_slots'] == {}
        assert runtime.accepted_task_catalog == accepted
    finally:
        runtime.close()
    assert len(env.native.launches) == len(full_run['first']['launches'])
    hermetic(env)


# --- 2. Claude usage limit: pool hold, same-pool deferral, hold expires, publication --

def test_claude_usage_limit_holds_pool_defers_peer_and_still_publishes(make_env, monkeypatch):
    env = make_env()
    # N6 (inverse): a Warden containment variable never becomes the seat identity.
    monkeypatch.setenv('COCHEM_WARDEN_CONTAINMENT_ID', 'e' * 32)
    clock = Clock(monkeypatch)
    env.native.faults[('claude', 'claude-haiku-5-5', 'medium')] = 'quota429'

    def expire_hold(record):
        if record['provider'] != 'claude' and not clock.skew and any(r['fault'] for r in env.native.launches):
            clock.skew = 301.0  # Past the 300 s quota cooldown, before publication.
    env.native.before_launch = expire_hold
    result, output = env.run_phase()
    assert result['status'] == READY and result['publication_state'] == 'COMMITTED', result
    assert result['all_routes_usable'] is False and result['coverage_holds'] > 0
    assert clock.skew == 301.0
    evidence = {(row['provider'], row['model'], row['reasoning_effort']): row for row in env.evidence()}
    assert evidence[('claude', 'claude-haiku-5-5', 'medium')]['status'] == 'AVAILABILITY_WAIT'
    assert evidence[('claude', 'claude-haiku-5-5', 'medium')]['failure_category'] == 'quota'
    assert evidence[('codex', 'gpt-6-luna', 'low')]['status'] == 'NATIVE_SELECTOR_ACCEPTED'
    assert evidence[('gemini', 'gemini-3.8-flash', 'low')]['status'] == 'NATIVE_SELECTOR_ACCEPTED'
    [deferred] = env.holds()
    assert (deferred['model'], deferred['status'], deferred['scope'], deferred['resource_key']) == (
        'claude-sonnet-5-5', 'AVAILABILITY_WAIT_UNTESTED', 'pool', 'claude')
    assert deferred['failure_category'] == 'quota' and deferred['native_probe_executed'] is False
    assert ('claude', 'claude-sonnet-5-5', 'medium') not in {target_of(row) for row in env.probe_rows()}
    assert not any(row['model'] == 'claude-sonnet-5-5' for row in env.native.launches)
    assert [row['kind'] for row in env.native.launches if row['provider'] == 'claude'] == SEQUENCES['claude']
    pool = env.query("SELECT until_at FROM pipeline_route_holds WHERE scope='pool' AND resource_key='claude'")
    assert pool and all(until < time.time() for (until,) in pool)  # Expired before publication.
    accepted = json.loads((output / 'accepted-catalog.json').read_bytes())
    assert accepted['models']['haiku-med']['native_acceptance'] == 'AVAILABILITY_WAIT'
    assert accepted['models']['sonnet-med']['availability_evidence'] == 'AVAILABILITY_WAIT_UNTESTED'
    assert accepted['models']['luna-low']['native_acceptance'] == 'ACCEPTED'
    runtime = env.runtimes[0]
    assert runtime.containment_id == 'e' * 32 != runtime.catalog.containment_id
    assert {row['containment_id'] for row in env.probe_rows()} == {runtime.catalog.containment_id}
    assert env.occupancy() == 0 and all(env.ram_slots_empty().values())
    hermetic(env)


# --- 3. A probe failure after verified closure frees its seat; failed closure holds it --

@pytest.mark.parametrize('fault', ['extra_field', 'close_failure'])
def test_failed_codex_probe_holds_before_publication(make_env, fault):
    env = make_env()
    env.native.faults[('codex', 'gpt-6-luna', 'low')] = fault
    result, output = env.run_phase()
    held(result, output, 'catalog_acceptance',
         'OutputFormatError' if fault == 'extra_field' else 'WorkerCleanupError')
    assert result['failure']['target'] == {'provider': 'codex', 'model': 'gpt-6-luna', 'effort': 'low'}
    assert result['publication_state'] == 'NOT_COMMITTED' and result['runtime_resources_closed'] is True
    assert env.active_catalog() == (ACTIVE_DIGEST, None)
    rows = {target_of(row): row for row in env.probe_rows()}
    codex = rows[('codex', 'gpt-6-luna', 'low')]
    assert [e['status'] for e in env.evidence()] == ['NATIVE_SELECTOR_ACCEPTED'] * 2
    assert not any(row['provider'] == 'gemini' for row in env.native.launches)
    if fault == 'extra_field':
        # Runtime dispatch contract: the tree closed before the error, so the
        # seat is a cleaned failed probe and the launcher may restore r4.
        assert json.loads(codex['result_json'])['status'] == 'PROBE_HELD' and env.occupancy() == 0
        assert result['publication_proof']['catalog_probe_cleanup_verified'] is True and restore_authority(result)
        assert all(env.ram_slots_empty().values())
    else:
        assert codex['cleanup_at'] is None and env.occupancy() == 1
        assert result['publication_proof']['catalog_probe_cleanup_verified'] is False
        assert not restore_authority(result)
    hermetic(env)


# --- 4. A slow Codex sequence beyond 180 s but within the 600 s probe lease -------------

@pytest.mark.parametrize('lease', [600, 180])
def test_slow_codex_sequence_outlives_old_lease_only_with_new_lease(make_env, monkeypatch, lease):
    from cochem_pipeline import task_catalog_acceptance_428 as acceptance
    env = make_env(['luna-low'])
    if lease != 600:
        monkeypatch.setattr(acceptance, 'PROBE_LEASE_SECONDS', lease)  # The 865a29b lease.
    clock = Clock(monkeypatch, monotonic=True)

    def slow(record):
        if record['provider'] == 'codex':
            clock.skew += 34.0  # Each native step stays within its own 30/60 s bound.
    env.native.before_launch = slow
    result, output = env.run_phase()
    codex = next(row for row in env.probe_rows() if target_of(row)[0] == 'codex')
    assert [row['kind'] for row in env.native.launches if row['provider'] == 'codex'] == SEQUENCES['codex']
    assert clock.skew == 204.0
    if lease == 600:
        assert result['status'] == READY and result['publication_state'] == 'COMMITTED', result
        assert 180 < codex['cleanup_at'] - codex['reserved_at'] < 600
        assert json.loads(codex['result_json'])['status'] == 'NATIVE_SELECTOR_ACCEPTED'
    else:
        held(result, output, 'catalog_acceptance', 'ExecutionRevokedError')
        assert json.loads(codex['result_json'])['status'] == 'PROBE_HELD' and env.occupancy() == 0
        assert result['publication_state'] == 'NOT_COMMITTED' and restore_authority(result)
    hermetic(env)


# --- 5. Runtime constructor failure: read-only board proof, restore authority ---------

@pytest.mark.parametrize('stage', ['layout', 'ramdisk'])
def test_runtime_constructor_failure_proves_nothing_committed(make_env, monkeypatch, stage):
    from cochem_pipeline import ramdisk, windows
    env = make_env()
    def refuse(*args, **kwargs):
        raise (windows.WindowsIsolationError if stage == 'layout' else ramdisk.RamdiskError)('offline injected')
    if stage == 'layout':
        monkeypatch.setattr(windows, 'validate_layout', refuse)
    else:
        monkeypatch.setattr(ramdisk.RamdiskManager, 'ensure', refuse)
    board = env.job_db.read_bytes()
    result, output = env.run_phase()
    held(result, output, 'runtime_bootstrap', 'WindowsIsolationError' if stage == 'layout' else 'RamdiskError')
    assert result['runtime_constructed'] is False and result['runtime_resources_closed'] is True
    assert result['publication_state'] == 'NOT_COMMITTED' and restore_authority(result)
    proof = result['publication_proof']
    assert proof['active_policy_sha256'] == ACTIVE_DIGEST and proof['active_catalog_sha256'] is None
    assert env.native.launches == [] and env.probe_rows() == [] and len(env.runtimes) == 1
    if stage == 'layout':
        assert env.job_db.read_bytes() == board
    for partial in env.runtimes:  # The one-shot process exits; release the partial object here.
        for name in ('oracle', 'knowledge', 'store'):
            if hasattr(partial, name):
                getattr(partial, name).close()
    hermetic(env)


# --- 6. Candidate failure inside the publication transaction rolls back --------------

def test_candidate_failure_inside_publication_rolls_back_then_replays_without_probes(make_env, monkeypatch):
    from cochem_pipeline import owner_task_catalog_428 as owner
    env = make_env()
    original = owner.load_config
    def refuse_candidate(path):
        if Path(path).parent.name == 'phase-output':
            raise ValueError('offline injected candidate refusal')
        return original(path)
    monkeypatch.setattr(owner, 'load_config', refuse_candidate)
    result, output = env.run_phase()
    held(result, output, 'candidate_validation', 'ValueError')
    assert result['publication_state'] == 'NOT_COMMITTED' and result['catalog_published'] is False
    assert restore_authority(result) and env.active_catalog() == (ACTIVE_DIGEST, None)
    assert (output / 'accepted-catalog.json').is_file() and (output / 'pipeline.json').is_file()
    assert not any(row['consumed_at'] for row in env.probe_rows()) and len(env.evidence()) == 4
    launches = len(env.native.launches)
    monkeypatch.setattr(owner, 'load_config', original)
    replay, _ = env.run_phase('continuation-output')
    assert replay['status'] == READY and replay['publication_state'] == 'COMMITTED', replay
    assert len(env.native.launches) == launches
    hermetic(env)


# --- 7. runtime.close() raising after COMMIT: the only remaining post-COMMIT surface --

def test_runtime_close_failure_after_commit_is_a_committed_hold(make_env, monkeypatch):
    from cochem_pipeline.runtime import Runtime
    env = make_env()
    original = Runtime.close
    def close_then_fail(self):
        original(self)
        raise RuntimeError('offline injected post-commit closure failure')
    monkeypatch.setattr(Runtime, 'close', close_then_fail)
    result, output = env.run_phase()
    held(result, output, 'resource_drain', 'RuntimeError')
    assert result['publication_state'] == 'COMMITTED' and result['catalog_published'] is True
    assert result['runtime_resources_closed'] is False and not restore_authority(result)
    assert (output / 'accepted-catalog.json').is_file() and (output / 'pipeline.json').is_file()
    assert env.active_catalog()[1]['request_id'] == env.request['request_id']
    hermetic(env)


# --- 8. Negative proofs of the 865a29b behaviour -------------------------------------

def test_n1_frozen_run_acceptance_fails_on_missing_containment_attribute(make_env, frozen, monkeypatch):
    from cochem_pipeline import owner_task_catalog_428 as owner, task_catalog_acceptance_428 as acceptance
    env = make_env()
    old = frozen.function(acceptance, 'run_acceptance')
    # The frozen API had no publication hooks; only defect (a) is isolated here.
    monkeypatch.setattr(owner, 'run_acceptance', lambda runtime, request, **hooks: old(runtime, request))
    result, output = env.run_phase()
    held(result, output, 'catalog_acceptance', 'AttributeError')
    assert result['failure']['frames'][-1]['function'] == 'run_acceptance'
    assert not hasattr(env.runtimes[0], 'catalog_containment_id')
    assert result['publication_state'] == 'NOT_COMMITTED' and restore_authority(result)
    assert env.probe_rows() == [] and env.native.launches == []
    hermetic(env)


@pytest.mark.parametrize('readiness', ['live', '865a29b'])
def test_n2_frozen_codex_worker_path_without_contract(make_env, frozen, monkeypatch, readiness):
    from cochem_pipeline import native_effort, task_catalog_acceptance_428 as acceptance, worker
    env = make_env(bootstrap='no_codex_contracts')
    monkeypatch.setattr(native_effort, 'effort_contract', frozen.function(native_effort, 'effort_contract'))
    monkeypatch.setattr(worker.NativeRunner, 'run', frozen.function(worker, 'NativeRunner.run'))
    rejected = []
    if readiness == '865a29b':
        # 865a29b had no per-target contract readiness; routing/seat checks stay.
        monkeypatch.setattr(acceptance, 'require_target_contracts', lambda providers, request: None)
        original = acceptance.record_result
        def observed(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            except ValueError as exc:
                rejected.append(str(exc))
                raise
        monkeypatch.setattr(acceptance, 'record_result', observed)
    result, output = env.run_phase()
    held(result, output, 'catalog_acceptance', 'ValueError')
    assert result['publication_state'] == 'NOT_COMMITTED' and restore_authority(result)
    if readiness == 'live':
        # Now: refused before any seat or paid native process.
        assert result['failure']['frames'][-1]['function'] == 'require_target_contracts'
        assert env.probe_rows() == [] and env.native.launches == []
    else:
        # Old order: both Claude targets paid for, then the first Codex target fails.
        assert rejected == ['Task probe lacks exact native binary/effort/fence evidence']
        assert result['failure']['target'] == {'provider': 'codex', 'model': 'gpt-6-luna', 'effort': 'low'}
        assert [e['provider'] for e in env.evidence()] == ['claude', 'claude']
        assert [row['kind'] for row in env.native.launches if row['provider'] == 'codex'] == SEQUENCES['codex'][1:]
        codex = next(row for row in env.probe_rows() if target_of(row)[0] == 'codex')
        assert json.loads(codex['result_json'])['status'] == 'PROBE_HELD' and env.occupancy() == 0
        assert not any(row['provider'] == 'gemini' for row in env.native.launches)
    hermetic(env)


def test_n4_bootstrap_routed_to_baseline_is_refused_before_any_probe(make_env):
    from cochem_pipeline.routing import load_routing_policy
    env = make_env(bootstrap='baseline')
    assert load_routing_policy(env.bootstrap['routing']).digest == BASELINE_DIGEST
    result, output = env.run_phase()
    held(result, output, 'catalog_acceptance', 'ValueError')
    assert result['failure']['frames'][-1]['function'] == 'require_probe_readiness'
    assert result['publication_state'] == 'NOT_COMMITTED' and restore_authority(result)
    assert env.probe_rows() == [] and env.native.launches == []
    hermetic(env)


def test_n5_active_bootstrap_with_retired_gemini_binding_is_refused_before_runtime(make_env):
    env = make_env(bootstrap='retired_binding')
    result, output = env.run_phase()
    held(result, output, 'preconditions', 'ValueError')
    assert any(frame['function'] == 'validate_gemini_route_bindings' for frame in result['failure']['frames'])
    assert result['runtime_constructed'] is False and env.runtimes == []
    assert env.native.launches == [] and env.probe_rows() == []
    hermetic(env)


def test_n5_bootstrap_refusal_still_proves_restore_authority(make_env):
    """A bootstrap that never loads cannot have touched the board or any seat.

    The launcher restores r4 only from NOT_COMMITTED, closed runtime resources
    and the board identity proof (Test-OpRestoreAuthority, Restore-OpPrevious).
    """
    env = make_env(bootstrap='retired_binding')
    result, _ = env.run_phase()
    assert result['phase'] == 'preconditions' and result['runtime_constructed'] is False
    assert result['runtime_resources_closed'] is True and result['publication_state'] == 'NOT_COMMITTED', (
        'DEFECT owner_task_catalog_428.run_owner_phase: a bootstrap load_config/pin failure leaves job_db None, '
        'so runtime_resources_closed=False and publication UNKNOWN; the launcher then cannot restore r4: '
        + json.dumps({key: result.get(key) for key in ('runtime_resources_closed', 'publication_state')}))
    assert restore_authority(result)
