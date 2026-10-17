"""r6 release inputs from the pinned r4 bundle: offline preparation only.

Host-input tests read the saved r4 bundle and the 2026-10-15 native binding
record (skipped when absent); nothing is executed or installed.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('operational_release_r6', ROOT / 'scripts/prepare_operational_release_428.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
task_spec = importlib.util.spec_from_file_location('task_catalog_release_r6', ROOT / 'scripts/prepare_task_catalog_428.py')
task_release = importlib.util.module_from_spec(task_spec)
task_spec.loader.exec_module(task_release)

PREP = Path(r'C:\Users\ansac\CoChem427\r428-operational-prep-20261015-v1')
host_inputs = pytest.mark.skipif(not (release.PREVIOUS_BUNDLE / 'launch-manifest.json').exists()
                                 or not (PREP / 'binary-bindings.json').exists(),
                                 reason='Saved r4 bundle / native binding record are host inputs')


def inputs():
    previous_raw, _ = release.read_current_baseline()
    candidate = release.bootstrap_from_current_428(previous_raw, target_root=release.R6_TARGET_ROOT)
    policy, basis = release.active_routing_policy()
    bindings = json.loads((PREP / 'binary-bindings.json').read_bytes())
    catalog = json.loads((ROOT / 'docs/4.2.8/routing-candidate.json').read_bytes())
    profiles = json.loads((PREP / 'candidate-profiles.json').read_bytes())
    return candidate, policy, basis, bindings, catalog, profiles


@host_inputs
def test_r6_bootstrap_routes_the_board_active_policy_with_exact_provider_edits(tmp_path):
    from cochem_pipeline.config import load_config
    candidate, policy, basis, bindings, catalog, _ = inputs()
    assert policy.digest == release.ACTIVE_POLICY_DIGEST and basis['baseline_policy_digest'] == release.BASELINE_POLICY_DIGEST
    routed = release.route_active_policy(candidate, policy, bindings, catalog)
    assert routed['routing'] == policy.as_dict()
    before, after = candidate['providers'], routed['providers']
    assert set(before['gemini']['model_bindings']) - set(after['gemini']['model_bindings']) == {'gemini-3.1-pro:high'}
    assert set(before['gemini']['effort_contracts']) - set(after['gemini']['effort_contracts']) == {'gemini-3.1-pro:high'}
    assert after['claude'] == before['claude']
    assert {k: v for k, v in after['codex'].items() if k != 'effort_contracts'} == before['codex']
    contracts = after['codex']['effort_contracts']
    expected = {f"{m['model']}:{m['effort']}" for m in catalog['models'].values() if m['provider'] == 'codex'}
    expected |= {f"{p['model']}:{p['reasoning_effort']}" for pairs in policy.as_dict()['tiers'].values()
                 for p in pairs if p['provider'] == 'codex'}
    assert set(contracts) == expected and len(contracts) >= 11
    for key, contract in contracts.items():
        effort = key.rsplit(':', 1)[1]
        assert contract == dict(arguments=['-c', 'model_reasoning_effort="' + effort + '"'], version_arguments=['--version'],
            executable_sha256=bindings['codex']['sha256'], version=bindings['codex']['version'],
            capability_reference=release.CODEX_CAPABILITY_REFERENCE, thinking_enabled=None, native_metadata=None)
    assert candidate['providers']['codex'].get('effort_contracts') is None  # input untouched
    path = tmp_path / 'pipeline.json'
    path.write_text(json.dumps(routed), encoding='utf-8')
    parsed = load_config(str(path))
    assert parsed.routing.digest == release.ACTIVE_POLICY_DIGEST and parsed.catalog_activation is True
    assert parsed.task_planning is None and parsed.max_execution_slots == 4
    assert all(routed['knowledge'][key].startswith(release.R6_TARGET_ROOT + '\\source\\knowledge\\')
               for key in ('source_root', 'wiki_root', 'manifest_path'))


@host_inputs
@pytest.mark.parametrize('mutation', ['executable', 'claude_binary', 'extra_orphan', 'existing_codex_contracts'])
def test_r6_bootstrap_refuses_unreviewed_provider_drift(mutation):
    candidate, policy, _, bindings, catalog, _ = inputs()
    bindings = deepcopy(bindings)
    if mutation == 'executable':
        bindings['codex']['executable'] = r'C:\other\codex.exe'
    elif mutation == 'claude_binary':
        bindings['claude']['sha256'] = '0' * 64
    elif mutation == 'extra_orphan':
        candidate['providers']['gemini']['model_bindings']['gemini-9-test:high'] = 'gemini-9-test-high'
    else:
        candidate['providers']['codex']['effort_contracts'] = {}
    with pytest.raises(ValueError):
        release.route_active_policy(candidate, policy, bindings, catalog)


def test_preparers_refuse_working_tree_code_that_is_not_the_packaged_commit():
    with pytest.raises(ValueError, match='exact packaged'):
        release.require_committed_tree(ROOT, 'HEAD')
    with pytest.raises(ValueError, match='differ from the packaged commit'):
        release.require_committed_tree(ROOT, 'a' * 40)  # not an object in this repository
    assert task_release.require_committed_tree.__name__ == 'require_committed_tree'


def head_commit():
    import subprocess
    return subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                          check=True, timeout=30).stdout.strip()


@host_inputs
def test_r6_request_targets_the_active_policy_with_evidence_for_every_target(tmp_path, monkeypatch):
    checked = []
    monkeypatch.setattr(task_release, 'require_committed_tree', lambda repo, commit: checked.append(commit))
    commit = head_commit()
    candidate, policy, _, bindings, catalog, profiles = inputs()
    routed = release.route_active_policy(candidate, policy, bindings, catalog)
    manifest = task_release.prepare_task_catalog_release(tmp_path / 'r6', configuration=routed, catalog=catalog,
        binary_bindings=bindings, request_id='1' * 32, source_commit=commit, allow_partial_publication=True,
        candidate_profile_ids=profiles, expected_policy_digest=release.ACTIVE_POLICY_DIGEST)
    request = json.loads((tmp_path / 'r6' / 'task-catalog-request.json').read_bytes())
    assert request['previous_policy_digest'] == release.ACTIVE_POLICY_DIGEST
    assert request['previous_task_catalog_sha256'] is None and request['activation_authorized'] is False
    assert manifest['previous_policy_digest'] == release.ACTIVE_POLICY_DIGEST and manifest['probe_targets'] == 28
    assert checked == [commit]
    # The catalog that sizes targets and contracts must be the packaged commit's.
    altered = deepcopy(catalog)
    altered['generation'] = altered['generation'] + '-edited'
    with pytest.raises(ValueError, match='packaged commit routing candidate'):
        task_release.prepare_task_catalog_release(tmp_path / 'altered', configuration=routed, catalog=altered,
            binary_bindings=bindings, request_id='4' * 32, source_commit=commit, allow_partial_publication=True,
            candidate_profile_ids=profiles, expected_policy_digest=release.ACTIVE_POLICY_DIGEST)
    assert not (tmp_path / 'altered').exists()
    # The d5d6094 mistake: a request built from the baseline routing is refused offline.
    with pytest.raises(ValueError, match='board-active policy'):
        task_release.prepare_task_catalog_release(tmp_path / 'baseline', configuration=candidate, catalog=catalog,
            binary_bindings=bindings, request_id='2' * 32, source_commit=commit, allow_partial_publication=True,
            candidate_profile_ids=profiles, expected_policy_digest=release.ACTIVE_POLICY_DIGEST)
    # Without Codex contracts no Codex probe could ever record acceptable evidence.
    stripped = deepcopy(routed)
    stripped['providers']['codex'].pop('effort_contracts')
    with pytest.raises(ValueError, match='effort evidence'):
        task_release.prepare_task_catalog_release(tmp_path / 'stripped', configuration=stripped, catalog=catalog,
            binary_bindings=bindings, request_id='3' * 32, source_commit=commit, allow_partial_publication=True,
            candidate_profile_ids=profiles, expected_policy_digest=release.ACTIVE_POLICY_DIGEST)
    assert not (tmp_path / 'baseline').exists() and not (tmp_path / 'stripped').exists()


REPORT = b'....\n700 passed in 12.00s\n'


def evidence(**changes):
    value = dict(schema=release.SOURCE_TEST_SCHEMA, source_commit='a' * 40, runner='scripts/run_source_tests_428.py',
                 status='PASSED', failed=0, passed=700, modules=sorted(release.REQUIRED_SOURCE_TEST_MODULES),
                 source_test_report_sha256=hashlib.sha256(REPORT).hexdigest(), host_acceptance_executed=False)
    value.update(changes)
    return value


@pytest.mark.parametrize('changes', [dict(status='FAILED'), dict(failed=1), dict(source_commit='c' * 40),
    dict(passed=0), dict(modules=[]), dict(modules=['../outside.py']), dict(host_acceptance_executed=True),
    dict(modules=sorted(release.REQUIRED_SOURCE_TEST_MODULES)[1:]),
    dict(source_test_report_sha256='short'), dict(source_test_report_sha256='c' * 64), dict(extra=True)])
def test_source_test_gate_requires_a_passed_report_for_the_exact_commit(tmp_path, changes):
    (tmp_path / 'source-tests.log').write_bytes(REPORT)
    good = tmp_path / 'good.json'
    good.write_text(json.dumps(evidence()))
    assert release.read_source_test_evidence(good, 'a' * 40) == good.read_bytes()
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps(evidence(**changes)))
    with pytest.raises(ValueError, match='PASSED report'):
        release.read_source_test_evidence(bad, 'a' * 40)
    (tmp_path / 'source-tests.log').write_bytes(REPORT + b'edited')
    with pytest.raises(ValueError, match='report missing or changed'):
        release.read_source_test_evidence(good, 'a' * 40)


def test_recorder_binds_a_clean_serialized_run_and_preserves_failures(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('record_source_tests_r6', ROOT / 'scripts/record_source_tests_428.py')
    recorder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recorder)
    assert recorder.summarize('x\n600 passed, 2 skipped in 3.10s\n') == 600
    for text in ('1 failed, 600 passed in 3.1s', '600 passed, 1 error in 3.1s', 'no summary', '0 passed in 1s'):
        with pytest.raises(ValueError):
            recorder.summarize(text)
    trees = []
    monkeypatch.setattr(recorder, 'require_committed_tree', lambda root, commit, paths: trees.append((commit, paths)))
    modules = sorted(release.REQUIRED_SOURCE_TEST_MODULES)
    module = 'pipeline_tests/test_operational_release_r6_428.py'
    calls = []
    def passing(argv, **kwargs):
        calls.append(argv)
        return type('Done', (), dict(returncode=0, stdout=b'....\n4 passed in 1.00s\n', stderr=b''))()
    result = recorder.record(tmp_path / 'ok', modules, runner=passing)
    assert result['status'] == 'PASSED' and result['passed'] == 4 and result['modules'] == modules
    assert calls[0][2].endswith('run_source_tests_428.py') and module in calls[0]
    assert len(trees) == 2 and trees[0][1] == ()  # the whole committed tree, root pytest config included
    report = (tmp_path / 'ok' / 'source-tests.log').read_bytes()
    assert hashlib.sha256(report).hexdigest() == result['source_test_report_sha256']
    assert release.read_source_test_evidence(tmp_path / 'ok' / 'source-test-evidence.json', result['source_commit'])
    def failing(argv, **kwargs):
        return type('Done', (), dict(returncode=1, stdout=b'F\n1 failed in 1.00s\n', stderr=b''))()
    with pytest.raises(ValueError, match='did not pass'):
        recorder.record(tmp_path / 'bad', [module], runner=failing)
    assert (tmp_path / 'bad' / 'source-tests.log').exists() and not (tmp_path / 'bad' / 'source-test-evidence.json').exists()
    with pytest.raises(ValueError, match='existing pipeline_tests'):
        recorder.record(tmp_path / 'none', ['pipeline_tests/test_missing_x.py'], runner=passing)


def test_installer_and_constants_name_the_fresh_r6_root():
    installer = (ROOT / 'scripts' / release.INSTALLER).read_bytes()
    root, revision = release.RELEASES['r6']
    assert (root, revision) == (release.R6_TARGET_ROOT, release.R6_REVISION)
    assert root.rsplit('\\', 1)[1].encode() in installer and revision.encode() in installer
    assert b'20261015' not in installer
    assert release.RELEASES['r5'] == (release.TARGET_ROOT, release.REVISION)  # spent r5 recovery pins kept
    launcher = (ROOT / 'scripts' / 'run_operational_428_launch.ps1').read_text(encoding='utf-8')
    assert "Pipeline4.2.8-windows-20261017-r6';$revision='windows-20261017-428-v6'" in launcher
    assert release.ACTIVE_POLICY_DIGEST in launcher


def test_r6_release_requires_bindings_catalog_and_tests_together(tmp_path):
    with pytest.raises(ValueError, match='r6'):
        release.prepare_operational_release_428(tmp_path, tmp_path, tmp_path / 'a.json', tmp_path / 'out', ROOT,
                                                release='r6', binary_bindings={}, catalog=None, source_test_evidence=None)
    with pytest.raises(ValueError, match='Unknown'):
        release.prepare_operational_release_428(tmp_path, tmp_path, tmp_path / 'a.json', tmp_path / 'out', ROOT, release='r7')
    assert not (tmp_path / 'out').exists()
