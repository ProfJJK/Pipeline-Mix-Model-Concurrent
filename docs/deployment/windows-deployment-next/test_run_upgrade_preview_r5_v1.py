"""Inert harness for run_upgrade_preview_r5_v1.py and run-upgrade-preview-r5-v1.ps1 (BUILD-PREVIEW, r5 sitting S10).

Nothing here registers, runs or deletes a task, elevates, writes under C:\\Program Files or C:\\ProgramData, opens the
live job board or starts a pipeline. The Python helper runs in tmp_path fixture trees with its trusted preflight
(SYSTEM, interpreter and layout checks) replaced by a stub and its one child replaced either by a fake launcher or by
a stub interpreter: a copy of the repository venv launcher whose site-packages holds a fake cochem_pipeline that
prints fixture JSON. One integration test runs the REAL cochem_pipeline upgrade-preview of the repository source
against a temporary configuration pair and a temporary SQLite job board (in-process only: local files, no provider).
The wrapper's functions are extracted from its AST and dot-sourced into a throwaway Windows PowerShell 5.1 with every
system call stubbed (Task Scheduler COM objects, protected-path checks, file copies). The wrapper is never run with
-Apply (run_ps refuses any body that names -Apply), and top level only by the plan-mode smoke tests at the end, through
ps_toplevel_smoke.py (stubbed host; it refuses -Apply as well).
"""
import ctypes
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

import ps_toplevel_smoke as smoke

ROOT = Path(__file__).parent
RUNNER = ROOT / 'run_upgrade_preview_r5_v1.py'
SCRIPT = ROOT / 'run-upgrade-preview-r5-v1.ps1'
V22 = ROOT / 'retarget-warden-r4.ps1'
V22_SHA256 = '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e'
RETARGET_R5 = ROOT / 'retarget-warden-r5.ps1'
REGISTER = ROOT / 'register-stopped-warden-r3.ps1'
CHECK_R3 = ROOT / 'check-worker-native-status-r3.ps1'
INSPECTION = ROOT / 'protected-code-inspection-v4.ps1'
COPY_HELPER = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
REPO = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent')
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
COCHEM = Path(r'C:\Program Files\CoChem')
R4_ROOT = COCHEM / 'Pipeline4.2.7-windows-20261009-r4'
ATTEMPT = 'c' * 32
NONCE = 'd' * 32
ROOT_NAME = 'UpgradePreview4.2.7-windows-20261011-r5-v1-' + ATTEMPT
SDDL = 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'
R5_REPAIRS = ['src/cochem_pipeline/agy_protocol.py', 'src/cochem_pipeline/worker.py', 'src/cochem_pipeline/config.py',
              'src/cochem_supervisor/runner.py', 'src/cochem_pipeline/store.py', 'src/cochem_pipeline/coding.py',
              'src/cochem_pipeline/service.py', 'src/cochem_pipeline/operator_views.py', 'src/cochem_pipeline/knowledge.py',
              'src/cochem_pipeline/controller_guard.py', 'src/cochem_pipeline/runtime.py', 'src/cochem_pipeline/failures.py',
              'src/cochem_pipeline/__main__.py']
WRAPPER_FUNCTIONS = ['Import-ReviewedFunctions', 'Set-PreviewConstants', 'Assert-PreviewParameters', 'Initialize-PreviewHost',
                     'Assert-PreviewApplyIdentity', 'Import-PreviewHelpers', 'Connect-TaskFolder', 'Get-PreviewTaskArguments',
                     'New-PreviewNonce', 'Get-TaskPresence', 'Get-DaemonTaskObservations', 'Resolve-R5Install', 'Assert-CurrentConfig',
                     'Resolve-Candidate', 'Get-ProviderDigests', 'New-PreviewContext', 'New-PreviewTaskDefinition', 'Assert-PreviewTaskRegistration',
                     'Wait-PreviewTaskInstance', 'Assert-CompletedPreviewTask', 'Test-PreviewChangeEntries', 'Get-PreviewGate', 'Test-ProviderDigestMap',
                     'Assert-PreviewFailureMetadata', 'Assert-PreviewReceipt', 'New-PreviewSummary', 'Invoke-UpgradePreview',
                     'Write-PreviewOutcome', 'Get-PreviewPlan', 'Invoke-UpgradePreviewMain']
RETARGET_IMPORTS = ['Test-Sha256Text', 'Get-JsonMember', 'Get-JsonProperty', 'Get-JsonListField', 'Get-R5RootCandidates', 'Find-R5Root',
                    'Assert-R5InstalledBindings', 'Assert-R5Config', 'Assert-StagingReceipt', 'Read-JsonControl']
# Functions the imported set may call that the wrapper takes from elsewhere (hash-pinned) or that are cmdlets.
PROVIDED_ELSEWHERE = {'Read-R3Control', 'Read-R3Text', 'Test-ExactBool', 'Test-ExactInt'}


def load():
    spec = importlib.util.spec_from_file_location('run_upgrade_preview_r5_v1', RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


m = load()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path) -> str:
    return sha(Path(path).read_bytes())


def psq(value) -> str:
    return str(value).replace("'", "''")


# ----------------------------------------------------------------------------------------------- fixtures

COMMISSIONED_DOC = {'private_root': 'C:\\ProgramData\\CoChemPipeline427\\private',
                    'workers': {f'slot{i}': {'name': f'CoChem422Worker{i}', 'credential_target': f'CoChem422/slot{i}'} for i in range(1, 7)},
                    'providers': {'claude': {'executable': 'claude.exe', 'model': 'claude-x'},
                                  'gemini': {'executable': 'agy.exe', 'model': 'gemini-3.1-pro-preview', 'integration_hold': {'state': 'verification_pending'}}}}
COMMISSIONED = json.dumps(COMMISSIONED_DOC, indent=2).encode('utf-8')
ENABLED_DOC = json.loads(COMMISSIONED)
ENABLED_DOC['providers']['gemini'] = {'executable': 'agy.exe', 'model': 'gemini-3.1-pro-preview', 'protocol': 'agy-stream-json'}
ENABLED = json.dumps(ENABLED_DOC, indent=2).encode('utf-8')


def install_after(root: Path, commissioned_sha: str, python_sha: str) -> dict:
    """The r4 install-after.json field names (C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261009-r4) plus the r5 additions."""
    return {'schema': 'cochem-stopped-runtime-update/1', 'mode': 'FRESH_STOPPED_RUNTIME_READY', 'target_root': str(root),
            'previous_runtime_root': str(R4_ROOT), 'previous_install_receipt_sha256': '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502',
            'previous_source_manifest_sha256': '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189',
            'source_manifest_sha256': '7' * 64, 'source_files': 166, 'reviewed_repairs': list(R5_REPAIRS),
            'reviewed_repairs_sha256': {path: '%064x' % index for index, path in enumerate(R5_REPAIRS, 1)}, 'verified_unchanged': 153,
            'configuration_sha256': commissioned_sha, 'configuration_unchanged': True, 'only_config_change': None,
            'preserved_denial_receipt_sha256': '691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d',
            'managed_daemon_tasks': [{'name': 'CoChem-4.2.7-Warden', 'state': 'ENABLED=True;STATE=3;INSTANCES=0', 'references_new_root': False}],
            'preserved_worker_cleanup_verified': False, 'accounts_provisioned': 0, 'tasks_changed': 0, 'credentials_modified': False,
            'databases_modified': False, 'ram_modified': False, 'pipeline_started': False, 'activation_ready': False, 'holds': [],
            'verified_entries': 15013,
            'verification': {'revision': {'schema': 'cochem-installed-revision/1', 'verified': True, 'read_only': True, 'files': 109,
                                          'source_sha256': '5' * 64, 'acceptance_files': 0, 'acceptance_sha256': None},
                             'configuration_parsed': True, 'ram_workspace_root': 'R:\\CoChem427-windows-20261007', 'no_system_or_model_execution': True},
            'runtime_bindings': {'pyvenv_sha256': '6' * 64, 'venv_python_sha256': python_sha,
                                 'base_python_sha256': 'd8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa',
                                 'base_root': 'C:\\Program Files\\CoChem\\Toolchain4.2.7-windows-20261006\\Python312'}}


class Fixture:
    """A tmp_path stand-in for C:\\Program Files\\CoChem with the r5 install, both configurations and the preview root."""

    def __init__(self, base: Path, mode='held', install_mutate=None, python_from=None, proposed_bytes=None, text_mutate=None):
        base.mkdir(parents=True, exist_ok=True)
        self.base, self.mode = base, mode
        self.install = base / 'Pipeline4.2.7-windows-20261011-r5'
        self.python = self.install / '.venv' / 'Scripts' / 'python.exe'
        self.python.parent.mkdir(parents=True)
        if python_from is None:
            self.python.write_bytes(b'MZ fake r5 venv launcher')
        else:
            shutil.copyfile(python_from, self.python)
        self.current = base / 'WardenCommissioning4.2.7-windows-20261007-r3-v1' / 'pipeline.json'
        self.proposed = base / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
        for path, data in ((self.current, COMMISSIONED),
                           (self.proposed, proposed_bytes if proposed_bytes is not None else (COMMISSIONED if mode == 'held' else ENABLED))):
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        self.commissioned = sha(COMMISSIONED)
        after = install_after(self.install, self.commissioned, sha_file(self.python))
        if install_mutate:
            install_mutate(after)
        text = json.dumps(after, indent=4)
        if text_mutate:
            text = text_mutate(text)
        (self.install / 'install-after.json').write_text(text, encoding='utf-8')
        self.root = base / ROOT_NAME
        self.root.mkdir()
        self.settings = m.Settings(attempt=ATTEMPT, nonce=NONCE, install_root=self.install,
                                   install_after_sha256=sha_file(self.install / 'install-after.json'),
                                   venv_python_sha256=sha_file(self.python), current=self.current, current_sha256=self.commissioned,
                                   proposed=self.proposed, proposed_sha256=sha_file(self.proposed), mode=mode,
                                   output=self.root / 'upgrade-preview.json', preview_base=base, commissioned_sha256=self.commissioned)

    @property
    def current_info(self):
        return {'path': str(self.current.absolute()), 'sha256': self.commissioned}

    @property
    def proposed_info(self):
        return {'path': str(self.proposed.absolute()), 'sha256': sha_file(self.proposed)}

    def ps_context(self):
        # The wrapper's New-PreviewContext adds the per-provider digests of both bound files in enabled mode (B-F5).
        digests = (f"current_providers_sha256=(Get-ProviderDigests '{psq(self.current)}' '{self.commissioned}');"
                   f"proposed_providers_sha256=(Get-ProviderDigests '{psq(self.proposed)}' '{self.proposed_info['sha256']}')"
                   if self.mode == 'enabled' else 'current_providers_sha256=$null;proposed_providers_sha256=$null')
        return (f"$ctx=[ordered]@{{install_root='{psq(self.install)}';python='{psq(self.python)}';install_after_path='{psq(self.install / 'install-after.json')}';"
                f"install_after_sha256='{self.settings.install_after_sha256}';venv_python_sha256='{self.settings.venv_python_sha256}';"
                f"source_manifest_sha256='{'7' * 64}';revision_sha256='{'5' * 64}';reviewed_repairs=@();current_path='{psq(self.current_info['path'])}';"
                f"current_sha256='{self.commissioned}';proposed_path='{psq(self.proposed_info['path'])}';proposed_sha256='{self.proposed_info['sha256']}';"
                f"candidate_mode='{'GEMINI_HELD_COMMISSIONED_BYTES' if self.mode == 'held' else 'GEMINI_CONTRACT'}';mode='{self.mode}';{digests}}};"
                f"$script:configPin='{self.commissioned}';")


def clean_preview(current, proposed, config_changes=()):
    """The cochem-upgrade-preview/1 shape of cochem_pipeline.upgrade_preview (src/cochem_pipeline/upgrade_preview.py)."""
    workers = COMMISSIONED_DOC['workers']
    paths = [('configuration', current['path'], proposed['path']), ('private_root', 'C:\\ProgramData\\CoChemPipeline427\\private', None),
             ('job_board', 'C:\\ProgramData\\CoChemPipeline427\\private\\job_board.db', None), ('controller_token', 'C:\\Users\\ansac\\CoChem427\\controller.token', None),
             ('git_executable', 'C:\\Program Files\\Git\\cmd\\git.exe', None), ('provider_executable.gemini', 'C:\\Program Files\\CoChem\\Native4.2.7-windows-20261006\\agy.exe', None),
             ('worker_root.slot1', 'R:\\CoChem427-windows-20261007\\slot1', None)]
    return {'schema': 'cochem-upgrade-preview/1', 'checked_at': 1791700000.25, 'read_only': True, 'native_models_executed': False,
            'current': dict(current), 'proposed': dict(proposed),
            'protected_paths': [{'key': key, 'before': before, 'after': after if after is not None else before,
                                 'changed': (after if after is not None else before) != before} for key, before, after in paths],
            'identities': [{'key': key, 'before': value, 'after': value, 'changed': False} for key, value in workers.items()],
            'configuration_changes': [{'key': key, 'before_sha256': 'a' * 64, 'after_sha256': 'b' * 64} for key in config_changes],
            'database': {'exists': True, 'workflows': [{'workflow_id': 'w-1', 'kind': 'planning', 'status': 'COMPLETED',
                                                        'captured_policy_action': 'preserve_immutable_capture', 'automatic_rewrite': False,
                                                        'routing_policy_sha256': 'e' * 64}],
                         'user_version': 0, 'path': 'C:\\ProgramData\\CoChemPipeline427\\private\\job_board.db',
                         'proposed_path': 'C:\\ProgramData\\CoChemPipeline427\\private\\job_board.db', 'actual_schema_sha256': 'f' * 64,
                         'proposed_schema_sha256': 'f' * 64, 'proposed_user_version': 0,
                         'schema_versioning': 'DDL content hash; initialization preserves existing user_version', 'schema_changes': [],
                         'migration_executed': False},
            'rollback_prerequisites': [{'id': 'quiesced_workers', 'required': True, 'verified': False, 'detail': 'Stop and disable managed tasks'},
                                       {'id': 'job_board_online_backup', 'required': True, 'verified': False,
                                        'path': 'C:\\ProgramData\\CoChemPipeline427\\private\\job_board.db', 'detail': 'Use SQLite backup'}],
            'ready_to_deploy': False, 'remaining_action': 'Validate backups'}


def encode(preview) -> bytes:
    return (json.dumps(preview, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


class FakeLauncher:
    def __init__(self, stdout=b'', stderr=b'', exit_code=0, timed_out=False, raises=None, side_effect=None):
        self.result = {'stdout': stdout, 'stderr': stderr, 'exit_code': exit_code, 'timed_out': timed_out, 'elapsed_ms': 12}
        self.raises, self.side_effect, self.calls = raises, side_effect, []

    def __call__(self, argv, cwd, timeout):
        self.calls.append((list(argv), Path(cwd), timeout))
        if self.side_effect:
            self.side_effect()
        if self.raises:
            raise self.raises
        return dict(self.result)


def stub_preflight(settings):
    return {'system_sid': 'S-1-5-18', 'interpreter': str(settings.install_root / '.venv' / 'Scripts' / 'python.exe')}


def run_fixture(fx, preview=None, launcher=None):
    launcher = launcher or FakeLauncher(stdout=encode(preview))
    code = m.run(fx.settings, preflight=stub_preflight, launcher=launcher)
    receipt = json.loads((fx.root / 'upgrade-preview-receipt.json').read_text(encoding='ascii'))
    held_path = fx.root / 'upgrade-preview-held.json'
    held = json.loads(held_path.read_text(encoding='ascii')) if held_path.exists() else None
    return SimpleNamespace(code=code, receipt=receipt, held=held, launcher=launcher, files=sorted(p.name for p in fx.root.iterdir()))


# ----------------------------------------------------------------------------------------------- helper: pass paths

@pytest.mark.parametrize('mode,changes', [('held', ()), ('enabled', ('providers',)), ('enabled', ())])
def test_gate_passes_on_a_clean_preview_and_writes_receipt_and_output_only(tmp_path, mode, changes):
    fx = Fixture(tmp_path / 'fx', mode)
    stdout = encode(clean_preview(fx.current_info, fx.proposed_info, changes))
    result = run_fixture(fx, launcher=FakeLauncher(stdout=stdout, stderr=b'INFO harmless\n'))
    r = result.receipt
    assert result.code == 0 and r['status'] == 'UPGRADE_PREVIEW_GATE_PASSED' and result.held is None
    assert result.files == ['upgrade-preview-receipt.json', 'upgrade-preview.json', 'upgrade-preview.stderr.txt']
    assert (fx.root / 'upgrade-preview.json').read_bytes() == stdout and r['preview_sha256'] == sha(stdout) and r['preview_path'] == 'upgrade-preview.json'
    assert (fx.root / 'upgrade-preview.stderr.txt').read_bytes() == b'INFO harmless\n'
    assert r['gate'] == {'passed': True, 'reasons': [], 'mode': mode} and r['failure'] is None and r['held_record_path'] is None
    assert r['schema'] == 'cochem-upgrade-preview-r5-receipt/1' and r['attempt'] == ATTEMPT and r['nonce'] == NONCE and r['system_sid'] == 'S-1-5-18'
    assert r['helper_sha256'] == sha_file(RUNNER) and r['install_after_sha256'] == fx.settings.install_after_sha256
    assert r['install_mode'] == 'FRESH_STOPPED_RUNTIME_READY' and r['venv_python'] == str(fx.python) and r['venv_python_sha256'] == sha_file(fx.python)
    assert r['reviewed_repairs'] == R5_REPAIRS and r['source_manifest_sha256'] == '7' * 64 and r['revision_sha256'] == '5' * 64
    assert r['current'] == {**fx.current_info, 'length': len(COMMISSIONED), 'providers_sha256': m.provider_digests(COMMISSIONED_DOC)}
    assert r['proposed']['sha256'] == fx.proposed_info['sha256'] and r['proposed']['providers_sha256'] == m.provider_digests(json.loads(fx.proposed.read_bytes()))
    assert r['config_mode'] == mode and r['commissioned_sha256'] == fx.commissioned
    assert r['summary'] == {'identities_changed': [], 'protected_paths_changed': [], 'configuration_path_swap_accepted': True,
                            'configuration_change_keys': list(changes), 'schema_change_count': 0, 'database_exists': True, 'workflows_captured': 1,
                            'providers_changed': ['gemini'] if mode == 'enabled' else []}
    assert [p['id'] for p in r['rollback_prerequisites']] == ['quiesced_workers', 'job_board_online_backup']
    assert r['child'] == {'exit_code': 0, 'timed_out': False, 'elapsed_ms': 12, 'stdout_bytes': len(stdout), 'stdout_sha256': sha(stdout),
                          'stderr_bytes': 14, 'stderr_sha256': sha(b'INFO harmless\n')}
    assert r['native_models_executed'] is False and r['tasks_changed'] == 0 and r['automatic_retry_allowed'] is False
    assert (fx.root / 'upgrade-preview-receipt.json').read_bytes().isascii()


def test_the_one_child_is_the_bound_r5_interpreter_running_the_upgrade_preview_cli(tmp_path):
    fx = Fixture(tmp_path / 'fx')
    result = run_fixture(fx, clean_preview(fx.current_info, fx.proposed_info))
    assert len(result.launcher.calls) == 1
    argv, cwd, timeout = result.launcher.calls[0]
    assert argv == [str(fx.python), '-I', '-B', '-X', 'utf8', '-m', 'cochem_pipeline', 'upgrade-preview',
                    '--current-config', str(fx.current), '--proposed-config', str(fx.proposed)]
    assert cwd == fx.root and timeout == 120 and result.receipt['command'] == argv


# ----------------------------------------------------------------------------------------------- helper: gate failures

def _set(path, value):
    def mutate(p):
        target = p
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def _pop(path):
    def mutate(p):
        target = p
        for key in path[:-1]:
            target = target[key]
        target.pop(path[-1])
    return mutate


def _identity_changed(p):
    p['identities'][0]['after'] = {'name': 'OtherWorker', 'credential_target': 'CoChem422/slot1'}
    p['identities'][0]['changed'] = True


def _path_changed(p):
    row = next(r for r in p['protected_paths'] if r['key'] == 'job_board')
    row.update(after='D:\\elsewhere\\job_board.db', changed=True)


def _configuration_swap_wrong(p):
    p['protected_paths'][0].update(after='C:\\other\\pipeline.json', changed=True)


def _many(*mutations):
    def mutate(p):
        for item in mutations:
            item(p)
    return mutate


GATE_CASES = {
    'read_only_false': ('held', (), _set(['read_only'], False), ['READ_ONLY_NOT_TRUE']),
    'read_only_string': ('held', (), _set(['read_only'], 'true'), ['READ_ONLY_NOT_TRUE']),
    'read_only_missing': ('held', (), _pop(['read_only']), ['READ_ONLY_NOT_TRUE']),
    'native_models_executed_true': ('held', (), _set(['native_models_executed'], True), ['NATIVE_MODELS_EXECUTED']),
    'native_models_executed_missing': ('held', (), _pop(['native_models_executed']), ['NATIVE_MODELS_EXECUTED']),
    'identity_changed': ('held', (), _identity_changed, ['IDENTITIES_CHANGED']),
    'identities_not_a_list': ('held', (), _set(['identities'], None), ['IDENTITIES_MALFORMED']),
    'identity_changed_flag_not_bool': ('held', (), _set(['identities', 0, 'changed'], 'no'), ['IDENTITIES_MALFORMED']),
    'protected_path_changed': ('held', (), _path_changed, ['PROTECTED_PATHS_CHANGED']),
    'configuration_swap_to_another_file': ('held', (), _configuration_swap_wrong, ['PROTECTED_PATHS_CHANGED']),
    'protected_paths_missing': ('held', (), _pop(['protected_paths']), ['PROTECTED_PATHS_MALFORMED']),
    'schema_changes_nonempty': ('held', (), _set(['database', 'schema_changes'], [{'object': 'table:obsolete_extra', 'action': 'preserve_unmanaged_object',
                                                                                 'before_sha256': 'a' * 64, 'after_sha256': 'b' * 64}]), ['SCHEMA_CHANGES_PRESENT']),
    'schema_changes_missing': ('held', (), _pop(['database', 'schema_changes']), ['SCHEMA_CHANGES_MALFORMED']),
    'database_exists_false': ('held', (), _set(['database', 'exists'], False), ['DATABASE_NOT_PRESENT']),
    'database_exists_missing': ('held', (), _pop(['database', 'exists']), ['DATABASE_NOT_PRESENT']),
    'database_missing': ('held', (), _pop(['database']), ['DATABASE_MALFORMED']),
    'migration_executed': ('held', (), _set(['database', 'migration_executed'], True), ['MIGRATION_EXECUTED']),
    'configuration_key_workers': ('enabled', ('providers', 'workers'), None, ['CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS']),
    'configuration_key_routing_only': ('enabled', ('routing',), None, ['CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS']),
    'held_mode_providers_change': ('held', ('providers',), None, ['CONFIGURATION_CHANGES_IN_HELD_MODE']),
    'held_mode_two_changes': ('held', ('providers', 'timeout_seconds'), None, ['CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS', 'CONFIGURATION_CHANGES_IN_HELD_MODE']),
    'configuration_changes_malformed': ('enabled', (), _set(['configuration_changes'], [{'before_sha256': 'a' * 64}]), ['CONFIGURATION_CHANGES_MALFORMED']),
    'preview_schema_wrong': ('held', (), _set(['schema'], 'cochem-upgrade-preview/2'), ['PREVIEW_SCHEMA_INVALID']),
    'current_sha_differs': ('held', (), _set(['current', 'sha256'], '0' * 64), ['CURRENT_BINDING_DIFFERS']),
    'proposed_path_differs': ('enabled', ('providers',), _set(['proposed', 'path'], 'C:\\elsewhere\\pipeline.json'), ['PROPOSED_BINDING_DIFFERS']),
    'several_at_once': ('held', (), _many(_set(['read_only'], False), _identity_changed, _set(['database', 'exists'], False)),
                        ['READ_ONLY_NOT_TRUE', 'IDENTITIES_CHANGED', 'DATABASE_NOT_PRESENT']),
}


def gate_preview(fx, case):
    _, changes, mutate, _ = GATE_CASES[case]
    preview = clean_preview(fx.current_info, fx.proposed_info, changes)
    if mutate:
        mutate(preview)
    return preview


@pytest.mark.parametrize('case', sorted(GATE_CASES))
def test_each_gate_condition_failing_alone_holds_with_its_reason(tmp_path, case):
    mode, _, _, reasons = GATE_CASES[case]
    fx = Fixture(tmp_path / 'fx', mode)
    stdout = encode(gate_preview(fx, case))
    result = run_fixture(fx, launcher=FakeLauncher(stdout=stdout))
    r = result.receipt
    assert result.code == 3 and r['status'] == 'UPGRADE_PREVIEW_GATE_FAILED'
    assert r['gate'] == {'passed': False, 'reasons': reasons, 'mode': mode} and r['failure'] is None
    assert (fx.root / 'upgrade-preview.json').read_bytes() == stdout, 'the failing preview is retained as evidence'
    assert result.held['reasons'] == reasons and result.held['phase'] == 'gate' and result.held['status'] == 'UPGRADE_PREVIEW_GATE_FAILED'
    assert r['held_record_path'] == 'upgrade-preview-held.json' and r['held_record_sha256'] == sha_file(fx.root / 'upgrade-preview-held.json')
    assert len(result.launcher.calls) == 1, 'no retry'


def _reordered_claude(document):
    document['providers']['claude'] = dict(reversed(list(document['providers']['claude'].items())))


PROVIDER_CASES = {
    # case: (change applied to the gemini-only enabled document, expected reasons, providers_changed)
    'gemini_only': (None, [], ['gemini']),
    'claude_changed_too': (_set(['providers', 'claude', 'model'], 'claude-other'), ['PROVIDERS_CHANGED_OUTSIDE_GEMINI'], ['claude', 'gemini']),
    'provider_added': (_set(['providers', 'codex'], {'executable': 'codex.exe', 'model': 'gpt-x'}), ['PROVIDERS_CHANGED_OUTSIDE_GEMINI'], ['codex', 'gemini']),
    'provider_removed': (_pop(['providers', 'claude']), ['PROVIDERS_CHANGED_OUTSIDE_GEMINI'], ['claude', 'gemini']),
    'claude_member_order': (_reordered_claude, ['PROVIDERS_CHANGED_OUTSIDE_GEMINI'], ['claude', 'gemini']),
}


def provider_case_bytes(case):
    document = json.loads(ENABLED)
    change = PROVIDER_CASES[case][0]
    if change:
        change(document)
    return json.dumps(document, indent=2).encode('utf-8')


@pytest.mark.parametrize('case', sorted(PROVIDER_CASES))
def test_enabled_mode_allows_only_providers_gemini_to_differ_between_the_bound_files(tmp_path, case):
    """Deploy audit B-F5: a preview that reports only a 'providers' change key used to pass with any provider changed."""
    _, reasons, changed = PROVIDER_CASES[case]
    fx = Fixture(tmp_path / 'fx', 'enabled', proposed_bytes=provider_case_bytes(case))
    result = run_fixture(fx, clean_preview(fx.current_info, fx.proposed_info, ('providers',)))
    r = result.receipt
    assert r['gate'] == {'passed': not reasons, 'reasons': reasons, 'mode': 'enabled'} and r['summary']['providers_changed'] == changed
    assert result.code == (3 if reasons else 0) and r['proposed']['providers_sha256'] == m.provider_digests(json.loads(fx.proposed.read_bytes()))
    assert (result.held is not None) is bool(reasons)


def test_provider_digests_and_the_enabled_gate_unit():
    digests = m.provider_digests(COMMISSIONED_DOC)
    assert sorted(digests) == ['claude', 'gemini'] and all(len(value) == 64 for value in digests.values())
    assert digests['claude'] == sha(json.dumps(COMMISSIONED_DOC['providers']['claude'], separators=(',', ':')).encode('ascii'))
    assert m.provider_digests({'providers': []}) is None and m.provider_digests([]) is None and m.provider_digests({}) is None
    current = {'path': 'c', 'sha256': '1' * 64, 'providers_sha256': digests}
    preview = clean_preview({'path': 'c', 'sha256': '1' * 64}, {'path': 'p', 'sha256': '2' * 64}, ('providers',))
    for proposed_digests, reasons in ((dict(digests, gemini='3' * 64), []), (dict(digests, claude='3' * 64), ['PROVIDERS_CHANGED_OUTSIDE_GEMINI']),
                                      (None, ['PROVIDER_DIGESTS_MALFORMED']), ({'gemini': 'not-a-digest'}, ['PROVIDER_DIGESTS_MALFORMED'])):
        gate = m.evaluate_gate(preview, 'enabled', current, {'path': 'p', 'sha256': '2' * 64, 'providers_sha256': proposed_digests})
        assert gate['reasons'] == reasons, (proposed_digests, gate)
    # Held mode binds the commissioned bytes on both sides; the per-provider rule is the enabled-mode rule.
    held = clean_preview({'path': 'c', 'sha256': '1' * 64}, {'path': 'p', 'sha256': '2' * 64})
    assert m.evaluate_gate(held, 'held', {'path': 'c', 'sha256': '1' * 64}, {'path': 'p', 'sha256': '2' * 64})['passed'] is True


def test_gate_reason_order_is_the_declared_order():
    for _, _, _, reasons in GATE_CASES.values():
        assert reasons == sorted(reasons, key=m.REASONS.index)
    assert len(set(m.REASONS)) == len(m.REASONS)


def test_held_record_content(tmp_path):
    fx = Fixture(tmp_path / 'fx', 'enabled')
    result = run_fixture(fx, gate_preview(fx, 'configuration_key_workers'))
    held = result.held
    assert held == {'schema': 'cochem-upgrade-preview-r5-held/1', 'attempt': ATTEMPT, 'nonce': NONCE, 'status': 'UPGRADE_PREVIEW_GATE_FAILED',
                    'phase': 'gate', 'reasons': ['CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS'], 'failure': None,
                    'receipt_path': 'upgrade-preview-receipt.json', 'preview_path': 'upgrade-preview.json',
                    'preview_sha256': result.receipt['preview_sha256'], 'stderr_path': 'upgrade-preview.stderr.txt',
                    'install_after_sha256': fx.settings.install_after_sha256, 'current_sha256': fx.commissioned,
                    'proposed_sha256': fx.proposed_info['sha256'], 'config_mode': 'enabled', 'automatic_retry_allowed': False,
                    'requires_owner_decision': True, 'owner_options': list(m.OWNER_OPTIONS), 'created_at_unix_ms': held['created_at_unix_ms']}
    assert any(option.startswith('R4-RESTORE') for option in held['owner_options']) and any('waiver' in option for option in held['owner_options'])
    assert (fx.root / 'upgrade-preview-held.json').read_bytes().isascii()


# ----------------------------------------------------------------------------------------------- helper: preview failures

MALFORMED_OUTPUTS = {'not_json': b'Traceback (most recent call last):\n', 'array': b'[1, 2]\n', 'duplicate_key': b'{"read_only": true, "read_only": false}',
                     'empty': b'', 'not_utf8': b'\xff\xfe{}', 'nan': b'{"schema": NaN}', 'two_documents': b'{}\n{}\n'}


@pytest.mark.parametrize('case', sorted(MALFORMED_OUTPUTS))
def test_malformed_or_absent_output_is_a_held_preview_failure(tmp_path, case):
    fx = Fixture(tmp_path / 'fx')
    stdout = MALFORMED_OUTPUTS[case]
    result = run_fixture(fx, launcher=FakeLauncher(stdout=stdout))
    r = result.receipt
    assert result.code == 4 and r['status'] == 'UPGRADE_PREVIEW_FAILED' and r['gate'] is None
    assert r['failure']['phase'] == 'preview_output' and r['failure']['reason'] == 'PREVIEW_OUTPUT_MALFORMED'
    assert not (fx.root / 'upgrade-preview.json').exists() and r['preview_path'] is None
    if stdout:
        assert (fx.root / 'upgrade-preview.stdout-invalid.bin').read_bytes() == stdout and r['invalid_stdout_path'] == 'upgrade-preview.stdout-invalid.bin'
    else:
        assert not (fx.root / 'upgrade-preview.stdout-invalid.bin').exists()
    assert result.held['reasons'] == ['PREVIEW_OUTPUT_MALFORMED'] and result.held['phase'] == 'preview_output'


@pytest.mark.parametrize('case,launcher,reason,phase', [
    ('nonzero_exit', FakeLauncher(stdout=b'', stderr=b'ValueError: Upgrade preview requires a bounded ordinary configuration file\n', exit_code=1), 'PREVIEW_EXIT_NONZERO', 'preview_launch'),
    ('timeout', FakeLauncher(stdout=b'{"schema": "cochem-up', stderr=b'', exit_code=None, timed_out=True), 'PREVIEW_TIMED_OUT', 'preview_launch'),
    ('launch_error', FakeLauncher(raises=FileNotFoundError(2, 'missing')), 'PREVIEW_LAUNCH_FAILED', 'preview_launch'),
])
def test_nonzero_exit_timeout_and_launch_errors_are_held_without_retry(tmp_path, case, launcher, reason, phase):
    fx = Fixture(tmp_path / 'fx')
    result = run_fixture(fx, launcher=launcher)
    r = result.receipt
    assert result.code == 4 and r['status'] == 'UPGRADE_PREVIEW_FAILED' and r['failure']['reason'] == reason and r['failure']['phase'] == phase
    assert len(launcher.calls) == 1 and result.held['reasons'] == [reason] and not (fx.root / 'upgrade-preview.json').exists()
    if case == 'nonzero_exit':
        assert r['child']['exit_code'] == 1 and (fx.root / 'upgrade-preview.stderr.txt').read_bytes().startswith(b'ValueError')
    if case == 'timeout':
        assert r['child']['timed_out'] is True and (fx.root / 'upgrade-preview.stdout-invalid.bin').read_bytes() == b'{"schema": "cochem-up'
    if case == 'launch_error':
        assert r['child'] is None and r['failure']['error_type'] == 'FileNotFoundError' and r['failure']['detail'] is None


def test_a_configuration_changed_during_the_preview_is_refused(tmp_path):
    fx = Fixture(tmp_path / 'fx', 'enabled')
    preview = clean_preview(fx.current_info, fx.proposed_info, ('providers',))
    launcher = FakeLauncher(stdout=encode(preview), side_effect=lambda: fx.proposed.write_bytes(ENABLED + b' '))
    result = run_fixture(fx, launcher=launcher)
    assert result.code == 4 and result.receipt['failure']['reason'] == 'CONFIG_BINDING_DIFFERS' and result.held is not None


INSTALL_CASES = {
    'install_after_sha_differs': (None, None, lambda s: dataclasses.replace(s, install_after_sha256='0' * 64)),
    'mode_partial': (_set(['mode'], 'PARTIAL'), None, None),
    'schema_v2': (_set(['schema'], 'cochem-stopped-runtime-update/2'), None, None),
    'target_root_other': (_set(['target_root'], 'C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261009-r4'), None, None),
    'configuration_sha_differs': (_set(['configuration_sha256'], '0' * 64), None, None),
    'configuration_unchanged_string': (_set(['configuration_unchanged'], 'true'), None, None),
    'holds_nonempty': (_set(['holds'], ['r5 build held']), None, None),
    'holds_missing': (_pop(['holds']), None, None),
    'tasks_changed_bool': (_set(['tasks_changed'], False), None, None),
    'pipeline_started': (_set(['pipeline_started'], True), None, None),
    'repairs_without_main': (lambda a: (a['reviewed_repairs'].remove('src/cochem_pipeline/__main__.py'),
                                        a['reviewed_repairs_sha256'].pop('src/cochem_pipeline/__main__.py')), None, None),
    'repair_pins_not_one_to_one': (lambda a: a['reviewed_repairs_sha256'].update({'src/cochem_pipeline/extra.py': '1' * 64}), None, None),
    'no_execution_flag_false': (_set(['verification', 'no_system_or_model_execution'], False), None, None),
    'venv_binding_differs': (_set(['runtime_bindings', 'venv_python_sha256'], '0' * 64), None, None),
    'duplicate_key': (None, lambda t: t.replace('"mode": "FRESH_STOPPED_RUNTIME_READY",', '"mode": "FRESH_STOPPED_RUNTIME_READY", "mode": "FRESH_STOPPED_RUNTIME_READY",', 1), None),
    'not_json': (None, lambda t: '{not json', None),
}


@pytest.mark.parametrize('case', sorted(INSTALL_CASES) + ['python_bytes_differ'])
def test_install_binding_failures_hold_before_any_launch(tmp_path, case):
    mutate, text, settings_change = INSTALL_CASES.get(case, (None, None, None))
    fx = Fixture(tmp_path / 'fx', install_mutate=mutate, text_mutate=text)
    if settings_change:
        fx.settings = settings_change(fx.settings)
    if case == 'python_bytes_differ':
        fx.python.write_bytes(b'MZ another launcher')
    launcher = FakeLauncher(stdout=encode(clean_preview(fx.current_info, fx.proposed_info)))
    result = run_fixture(fx, launcher=launcher)
    assert result.code == 4 and result.receipt['failure']['phase'] == 'install_binding'
    assert result.receipt['failure']['reason'] == 'INSTALL_BINDING_DIFFERS' and launcher.calls == []
    assert result.files == ['upgrade-preview-held.json', 'upgrade-preview-receipt.json']


CONFIG_CASES = {
    'current_sha_wrong': lambda fx: dataclasses.replace(fx.settings, current_sha256='0' * 64),
    'proposed_sha_wrong': lambda fx: dataclasses.replace(fx.settings, proposed_sha256='0' * 64),
    'current_not_commissioned': lambda fx: dataclasses.replace(fx.settings, commissioned_sha256='1' * 64, current_sha256=fx.commissioned),
    'held_with_other_bytes': lambda fx: dataclasses.replace(fx.settings, mode='held', proposed_sha256=sha(ENABLED)),
    'enabled_with_commissioned_bytes': lambda fx: dataclasses.replace(fx.settings, mode='enabled'),
}


@pytest.mark.parametrize('case', sorted(CONFIG_CASES))
def test_configuration_binding_failures_hold_before_any_launch(tmp_path, case):
    fx = Fixture(tmp_path / 'fx', 'held', proposed_bytes=(ENABLED if case == 'held_with_other_bytes' else None))
    fx.settings = CONFIG_CASES[case](fx)
    if case == 'current_not_commissioned':
        # The install binding names the commissioned pin; this case only reaches the configuration check when it agrees.
        after = json.loads((fx.install / 'install-after.json').read_text(encoding='utf-8'))
        after['configuration_sha256'] = '1' * 64
        (fx.install / 'install-after.json').write_text(json.dumps(after, indent=4), encoding='utf-8')
        fx.settings = dataclasses.replace(fx.settings, install_after_sha256=sha_file(fx.install / 'install-after.json'))
    launcher = FakeLauncher(stdout=b'{}')
    result = run_fixture(fx, launcher=launcher)
    assert result.code == 4 and result.receipt['failure'] == {'phase': 'config_binding', 'reason': 'CONFIG_BINDING_DIFFERS',
                                                            'error_type': 'PreviewRefusal', 'detail': result.receipt['failure']['detail']}
    assert launcher.calls == [] and result.held['reasons'] == ['CONFIG_BINDING_DIFFERS']


def test_an_existing_receipt_refuses_the_run_and_nothing_is_written(tmp_path):
    fx = Fixture(tmp_path / 'fx')
    existing = fx.root / 'upgrade-preview-receipt.json'
    existing.write_bytes(b'{"earlier": true}')
    launcher = FakeLauncher(stdout=encode(clean_preview(fx.current_info, fx.proposed_info)))
    with pytest.raises(FileExistsError):
        m.run(fx.settings, preflight=stub_preflight, launcher=launcher)
    assert existing.read_bytes() == b'{"earlier": true}' and launcher.calls == []
    assert sorted(p.name for p in fx.root.iterdir()) == ['upgrade-preview-receipt.json']


def test_an_existing_held_record_is_never_overwritten(tmp_path):
    fx = Fixture(tmp_path / 'fx')
    (fx.root / 'upgrade-preview-held.json').write_bytes(b'earlier')
    code = m.run(fx.settings, preflight=stub_preflight, launcher=FakeLauncher(stdout=encode(gate_preview(fx, 'read_only_false'))))
    receipt = json.loads((fx.root / 'upgrade-preview-receipt.json').read_text(encoding='ascii'))
    assert (fx.root / 'upgrade-preview-held.json').read_bytes() == b'earlier'
    assert code == 3 and receipt['status'] == 'UPGRADE_PREVIEW_GATE_FAILED'
    assert receipt['held_record_path'] is None and receipt['held_record_sha256'] is None, 'the receipt says the held record could not be written'


def test_preflight_refusal_writes_nothing(tmp_path):
    fx = Fixture(tmp_path / 'fx')

    def refuse(settings):
        raise m.PreviewRefusal('TRUSTED_PREFLIGHT', 'not SYSTEM')
    with pytest.raises(m.PreviewRefusal):
        m.run(fx.settings, preflight=refuse, launcher=FakeLauncher())
    assert list(fx.root.iterdir()) == []


def preflight_settings(base: Path, **change):
    root = base / ROOT_NAME
    settings = m.Settings(attempt=ATTEMPT, nonce=NONCE, install_root=base / 'Pipeline4.2.7-windows-20261011-r5', install_after_sha256='1' * 64,
                          venv_python_sha256='2' * 64, current=base / 'c.json', current_sha256=m.CONFIG_SHA256, proposed=base / 'p.json',
                          proposed_sha256='3' * 64, mode='held', output=root / 'upgrade-preview.json', preview_base=base)
    return dataclasses.replace(settings, **change)


def test_trusted_preflight_requires_the_root_layout_the_helper_copy_the_r5_interpreter_and_system(tmp_path):
    base = tmp_path
    good = preflight_settings(base)
    python = good.install_root / '.venv' / 'Scripts' / 'python.exe'
    helper = good.root / m.HELPER_NAME
    calls = []
    kwargs = dict(helper=helper, executable=python, isolated=True, no_bytecode=True, system_check=lambda s: calls.append(s))
    assert m.trusted_preflight(good, **kwargs)['system_sid'] == 'S-1-5-18' and len(calls) == 1
    refusals = {
        'root_parent': (dataclasses.replace(good, output=base / 'other' / ROOT_NAME / 'upgrade-preview.json'), {}),
        'root_name_other_attempt': (dataclasses.replace(good, output=base / ('UpgradePreview4.2.7-windows-20261011-r5-v1-' + 'e' * 32) / 'upgrade-preview.json'), {}),
        'output_name': (dataclasses.replace(good, output=good.root / 'other.json'), {}),
        'install_root_r4': (dataclasses.replace(good, install_root=base / 'Pipeline4.2.7-windows-20261009-r4'), {}),
        'helper_elsewhere': (good, {'helper': base / m.HELPER_NAME}),
        'interpreter_other': (good, {'executable': Path(sys.executable)}),
        'not_isolated': (good, {'isolated': False}),
        'writes_bytecode': (good, {'no_bytecode': False}),
    }
    for name, (settings, change) in refusals.items():
        with pytest.raises(m.PreviewRefusal) as caught:
            m.trusted_preflight(settings, **{**kwargs, **change})
        assert caught.value.reason == 'TRUSTED_PREFLIGHT', name
    with pytest.raises(RuntimeError):
        m.trusted_preflight(good, **{**kwargs, 'system_check': lambda s: (_ for _ in ()).throw(RuntimeError('not SYSTEM'))})


def test_require_system_refuses_a_cochem_package_outside_the_r5_install(tmp_path):
    pytest.importorskip('cochem_pipeline.windows')
    with pytest.raises(m.PreviewRefusal, match='not the installed r5 package'):
        m.require_system(preflight_settings(tmp_path))


def valid_argv(**change):
    values = {'--attempt': ATTEMPT, '--nonce': NONCE, '--install-after-sha256': '1' * 64, '--venv-python-sha256': '2' * 64,
              '--proposed-sha256': '3' * 64, '--mode': 'held'}
    values.update(change)
    argv = []
    for key, value in values.items():
        if value is not None:
            argv += [key, value]
    return argv


def test_arguments_default_to_the_real_paths_and_refuse_unbound_values():
    settings = m.settings_from_args(m.build_parser().parse_args(valid_argv()))
    assert settings.install_root == COCHEM / 'Pipeline4.2.7-windows-20261011-r5'
    assert settings.current == COCHEM / 'WardenCommissioning4.2.7-windows-20261007-r3-v1' / 'pipeline.json'
    assert settings.proposed == COCHEM / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
    assert settings.output == COCHEM / ROOT_NAME / 'upgrade-preview.json' and settings.current_sha256 == m.CONFIG_SHA256
    assert settings.preview_base == COCHEM and settings.commissioned_sha256 == m.CONFIG_SHA256 and settings.child_timeout == 120
    for change in ({'--attempt': '0' * 32}, {'--attempt': 'C' * 32}, {'--nonce': 'x'}, {'--proposed-sha256': 'A' * 64},
                   {'--current-sha256': '4' * 64}, {'--current': 'relative\\pipeline.json'}, {'--output': str(COCHEM / ROOT_NAME / 'other.json')}):
        with pytest.raises(m.PreviewRefusal):
            m.settings_from_args(m.build_parser().parse_args(valid_argv(**change)))
    with pytest.raises(SystemExit):
        m.build_parser().parse_args(valid_argv(**{'--mode': 'auto'}))


def test_main_on_this_host_is_refused_before_any_receipt(capsys):
    before = sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []
    assert m.main(valid_argv()) == 5
    error = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert error['status'] == 'PRE_RECEIPT_REFUSED' and error['reason'] == 'TRUSTED_PREFLIGHT'
    assert (sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []) == before


def test_runner_is_ascii_and_has_one_child_and_no_destructive_calls():
    text = RUNNER.read_text(encoding='utf-8')
    assert RUNNER.read_bytes().isascii() and text.count('subprocess.run(') == 1 and 'shell=True' not in text
    for forbidden in ('os.remove', 'unlink', 'rmtree', 'shutil', 'schtasks', 'taskkill', 'TerminateProcess', 'Popen(', "open('w", "'wb'", 'os.system'):
        assert forbidden not in text, forbidden
    assert text.count(".open('xb')") == 2, 'the receipt reservation and write_new are the only file creations'


# ----------------------------------------------------------------------------------------------- helper: stub interpreter (real child process)

STUB_MAIN = r'''import json, sys, time
from pathlib import Path
here = Path(__file__).parent
behavior = json.loads((here / 'behavior.json').read_text(encoding='utf-8'))
(here / 'record.json').write_text(json.dumps({'argv': sys.argv[1:], 'isolated': sys.flags.isolated, 'dont_write_bytecode': sys.dont_write_bytecode,
                                              'utf8_mode': sys.flags.utf8_mode, 'prefix': sys.prefix}), encoding='utf-8')
time.sleep(behavior.get('sleep', 0))
sys.stderr.write(behavior.get('stderr', ''))
if behavior.get('stdout_file'):
    sys.stdout.buffer.write(Path(behavior['stdout_file']).read_bytes())
sys.stdout.flush()
raise SystemExit(behavior.get('exit_code', 0))
'''


def stub_fixture(base: Path, mode='held'):
    fx = Fixture(base, mode, python_from=REPO / '.venv' / 'Scripts' / 'python.exe')
    shutil.copyfile(REPO / '.venv' / 'pyvenv.cfg', fx.install / '.venv' / 'pyvenv.cfg')
    package = fx.install / '.venv' / 'Lib' / 'site-packages' / 'cochem_pipeline'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('', encoding='ascii')
    (package / '__main__.py').write_text(STUB_MAIN, encoding='ascii')
    return fx, package


@pytest.mark.parametrize('case', ['pass', 'nonzero', 'malformed', 'timeout'])
def test_stub_interpreter_end_to_end_through_a_real_child_process(tmp_path, case):
    if not (REPO / '.venv' / 'Scripts' / 'python.exe').exists():
        pytest.skip('repository venv launcher absent')
    fx, package = stub_fixture(tmp_path / 'fx')
    stdout_file = tmp_path / 'stdout.json'
    stdout_file.write_bytes(encode(clean_preview(fx.current_info, fx.proposed_info)) if case != 'malformed' else b'not json\n')
    behavior = {'stdout_file': str(stdout_file), 'exit_code': 7 if case == 'nonzero' else 0, 'stderr': 'boom\n' if case == 'nonzero' else '',
                'sleep': 4 if case == 'timeout' else 0}
    (package / 'behavior.json').write_text(json.dumps(behavior), encoding='utf-8')
    if case == 'timeout':
        fx.settings = dataclasses.replace(fx.settings, child_timeout=1.0)
    code = m.run(fx.settings, preflight=stub_preflight)
    receipt = json.loads((fx.root / 'upgrade-preview-receipt.json').read_text(encoding='ascii'))
    if case == 'timeout':
        assert code == 4 and receipt['failure']['reason'] == 'PREVIEW_TIMED_OUT' and receipt['child']['timed_out'] is True
        # Ending the venv launcher also ended its interpreter child (the pipes closed long before the 4 s sleep).
        assert receipt['child']['elapsed_ms'] < 3500, receipt['child']
        return
    record = json.loads((package / 'record.json').read_text(encoding='utf-8'))
    assert record['argv'] == ['upgrade-preview', '--current-config', str(fx.current), '--proposed-config', str(fx.proposed)]
    assert record['isolated'] == 1 and record['dont_write_bytecode'] is True and record['utf8_mode'] == 1
    assert Path(record['prefix']).resolve() == (fx.install / '.venv').resolve(), 'the child ran inside the bound r5 venv'
    expected = {'pass': (0, 'UPGRADE_PREVIEW_GATE_PASSED', None), 'nonzero': (4, 'UPGRADE_PREVIEW_FAILED', 'PREVIEW_EXIT_NONZERO'),
                'malformed': (4, 'UPGRADE_PREVIEW_FAILED', 'PREVIEW_OUTPUT_MALFORMED')}[case]
    assert (code, receipt['status'], (receipt['failure'] or {}).get('reason')) == expected
    if case == 'pass':
        assert (fx.root / 'upgrade-preview.json').read_bytes() == stdout_file.read_bytes()
    if case == 'nonzero':
        assert receipt['child']['exit_code'] == 7
        assert (fx.root / 'upgrade-preview.stderr.txt').read_bytes() in (b'boom\n', b'boom\r\n')


# ----------------------------------------------------------------------------------------------- integration: the real module

def integration_document(base: Path, slots=6):
    """pipeline_tests/test_config.py config_document (synthetic, parser-valid) with temporary roots."""
    return {'private_root': str(base / 'private'),
            'slot_roots': {f'slot-{index}': str(base / 'slots' / str(index)) for index in range(slots)},
            'workers': {f'slot-{index}': {'name': f'CoChemWorker{index}', 'credential_target': f'CoChem/slot-{index}'} for index in range(slots)},
            'providers': {'codex': {'executable': 'codex.exe', 'model': 'gpt-6.1'}, 'claude': {'executable': 'claude.exe', 'model': 'sonnet'},
                          'gemini': {'executable': 'agy.exe', 'model': 'gemini-3.1-pro', 'protocol': 'terminal-json',
                                     'arguments': ['--headless', '--output-format', 'json', '--model', '{model}', '--workspace', '{workspace}'],
                                     'subscription_probe': {'arguments': ['fixture-status', '--json'], 'protocol': 'json-fields',
                                                            'expected': {'fixture.login': True, 'fixture.billing': 'subscription'}},
                                     'inference_only': {'arguments': ['fixture-no-tools', '{model}'], 'version_arguments': ['fixture-version'],
                                                        'executable_sha256': 'a' * 64, 'version': 'fixture-version',
                                                        'capability_reference': 'configuration parser fixture; not a native contract',
                                                        'disables_tools': True, 'disables_mcp': True, 'disables_hooks': True,
                                                        'disables_subagents': True, 'disables_model_fallback': True}}},
            'rules': [], 'token_file': str(base / 'operator' / 'controller.token'), 'operator_name': 'ExampleOperator'}


def test_real_upgrade_preview_output_shape_matches_the_gate(tmp_path):
    """The repository cochem_pipeline upgrade-preview (local files and a temporary SQLite only) through the helper's own
    command builder, launcher, parser and gate: held, enabled (providers.gemini only), enabled with providers.claude
    changed (held up since deploy audit B-F5) and a held-up identity change."""
    store_module = pytest.importorskip('cochem_pipeline.store')
    document = integration_document(tmp_path)
    raw = json.dumps(document, indent=2).encode('utf-8')
    current = tmp_path / 'commissioned' / 'pipeline.json'
    held = tmp_path / 'staged-held' / 'pipeline.json'
    gemini = tmp_path / 'staged-gemini' / 'pipeline.json'
    claude = tmp_path / 'staged-claude' / 'pipeline.json'
    workers = tmp_path / 'staged-workers' / 'pipeline.json'
    gemini_doc = json.loads(raw)
    gemini_doc['providers']['gemini']['inference_only']['capability_reference'] = 'configuration parser fixture; the staged gemini contract'
    claude_doc = json.loads(json.dumps(gemini_doc))
    claude_doc['providers']['claude']['model'] = 'opus'
    workers_doc = json.loads(raw)
    workers_doc['workers']['slot-0']['name'] = 'NewWorkerIdentity'
    for path, data in ((current, raw), (held, raw), (gemini, json.dumps(gemini_doc, indent=2).encode('utf-8')),
                       (claude, json.dumps(claude_doc, indent=2).encode('utf-8')), (workers, json.dumps(workers_doc, indent=2).encode('utf-8'))):
        path.parent.mkdir(parents=True)
        path.write_bytes(data)

    def preview(proposed, mode):
        result = m.launch(m.preview_command(Path(sys.executable), current, proposed), tmp_path, 120)
        assert result['exit_code'] == 0 and not result['timed_out'], result['stderr'][-2000:]
        value = m.strict_json(result['stdout'].decode('utf-8'))
        return value, m.evaluate_gate(value, mode, m.verify_config(current, sha_file(current)), m.verify_config(proposed, sha_file(proposed)))

    # No job board yet: the real module reports it absent (every expected table then reads as create_on_initialization)
    # and creates nothing.
    value, gate = preview(held, 'held')
    assert gate['reasons'] == ['DATABASE_NOT_PRESENT', 'SCHEMA_CHANGES_PRESENT'] and not (tmp_path / 'private').exists()
    assert {item['action'] for item in value['database']['schema_changes']} == {'create_on_initialization'}
    store = store_module.JobStore(tmp_path / 'private' / 'job_board.db')
    with sqlite3.connect(store.path) as conn:
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = sha_file(store.path)
    value, gate = preview(held, 'held')
    assert gate == {'passed': True, 'reasons': [], 'summary': {'identities_changed': [], 'protected_paths_changed': [],
                                                               'configuration_path_swap_accepted': True, 'configuration_change_keys': [],
                                                               'schema_change_count': 0, 'database_exists': True, 'workflows_captured': 0,
                                                               'providers_changed': []}}
    assert value['read_only'] is True and value['native_models_executed'] is False and value['database']['migration_executed'] is False
    assert len(value['identities']) == 6 and all(item['changed'] is False for item in value['identities']), 'every key is listed with a changed flag'
    assert [item['key'] for item in value['protected_paths'] if item['changed']] == ['configuration']
    assert {item['id'] for item in m.rollback_prerequisites(value)} >= {'quiesced_workers', 'job_board_online_backup'}
    value, gate = preview(gemini, 'enabled')
    assert gate['passed'] is True and gate['summary']['configuration_change_keys'] == ['providers'] and gate['summary']['providers_changed'] == ['gemini']
    # B-F5: the module reports only the top-level key 'providers'; a providers.claude change is now held up.
    value, gate = preview(claude, 'enabled')
    assert [item['key'] for item in value['configuration_changes']] == ['providers']
    assert gate['passed'] is False and gate['reasons'] == ['PROVIDERS_CHANGED_OUTSIDE_GEMINI'] and gate['summary']['providers_changed'] == ['claude', 'gemini']
    value, gate = preview(workers, 'enabled')
    assert gate['reasons'] == ['IDENTITIES_CHANGED', 'CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS'] and gate['summary']['identities_changed'] == ['slot-0']
    assert gate['summary']['providers_changed'] == []
    assert sha_file(store.path) == before, 'the real preview never mutates the job board'


# ----------------------------------------------------------------------------------------------- PowerShell wrapper

PRELUDE = r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")}
function Get-AstFunctionTexts {param([string]$Path,[string[]]$Names)
  $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if($e.Count){throw ($e|Out-String)}
  foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){if($null -eq $Names -or $Names -contains $f.Name){$f.Extent.Text}}}
foreach($x in Get-AstFunctionTexts '__SCRIPT__' $null){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts '__V22__' @('Test-ExactBool','Test-ExactInt')){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts '__REGISTER__' @('Assert-RegisteredTaskAcl')){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts '__RETARGET__' @(__RETARGET_NAMES__)){. ([scriptblock]::Create($x))}
$held=[Collections.Generic.List[IO.FileStream]]::new();$script:admin=$false
Set-PreviewConstants '__ATTEMPT__' '__WORKSPACE__'
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){throw ('Fixture control missing: '+$Path)}
  $bytes=[IO.File]::ReadAllBytes($Path);if($bytes.Length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $sha=[Security.Cryptography.SHA256]::Create();try{$actual=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
  if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  [pscustomobject]@{Stream=[IO.MemoryStream]::new($bytes);Sha256=$actual;Length=$bytes.Length}}
function Read-R3Text {param($Control)$Control.Stream.Position=0;$reader=[IO.StreamReader]::new($Control.Stream,[Text.Encoding]::UTF8,$true,4096,$true);try{$reader.ReadToEnd()}finally{$reader.Dispose()}}
function Write-RegistrationControl {param([string]$Path,[string]$Text)
  $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$raw=[Text.UTF8Encoding]::new($false).GetBytes($Text);$stream.Write($raw,0,$raw.Length)}finally{$stream.Dispose()}
  (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Open-VerifiedFile {param($Path,$Sha256,$Length) if((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256){throw ('Source digest changed: '+$Path)};$s=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);return ,$s}
function Invoke-Case {param([string]$Name,[scriptblock]$Body)
  try{$value=& $Body;'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=$value}|ConvertTo-Json -Depth 12 -Compress)}
  catch{'CASE '+([pscustomobject]@{case=$Name;ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Depth 12 -Compress)}}
'''


def run_ps(tmp_path: Path, body: str, timeout=240):
    assert not re.search(r'-Apply\b', body), 'the harness never passes -Apply'
    text = (PRELUDE.replace('__SCRIPT__', psq(SCRIPT)).replace('__V22__', psq(V22)).replace('__REGISTER__', psq(REGISTER))
            .replace('__RETARGET__', psq(RETARGET_R5)).replace('__RETARGET_NAMES__', ','.join(f"'{name}'" for name in RETARGET_IMPORTS))
            .replace('__ATTEMPT__', ATTEMPT).replace('__WORKSPACE__', psq(ROOT))) + body + '\nforeach($s in $held){$s.Dispose()}\n'
    tmp_path.mkdir(parents=True, exist_ok=True)
    case = tmp_path / ('case-%d.ps1' % len(list(tmp_path.glob('case-*.ps1'))))
    case.write_text(text, encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(case)],
                            capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, (result.stdout[-4000:], result.stderr[-4000:])
    cases = {}
    for line in result.stdout.splitlines():
        if line.startswith('CASE '):
            value = json.loads(line[5:])
            cases[value['case']] = value
    return cases


def test_wrapper_is_ascii_parses_under_ps51_and_has_one_invocation(tmp_path):
    body = rf'''$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('{psq(SCRIPT)}',[ref]$t,[ref]$e)
      $names=@($a.EndBlock.Statements|Where-Object {{$_ -is [Management.Automation.Language.FunctionDefinitionAst]}}|ForEach-Object {{$_.Name}})
      $top=@($a.EndBlock.Statements|Where-Object {{$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]}}|ForEach-Object {{$_.Extent.Text}})
      $params=@($a.ParamBlock.Parameters|ForEach-Object {{[ordered]@{{name=$_.Name.VariablePath.UserPath;default=$(if($_.DefaultValue){{$_.DefaultValue.Extent.Text}}else{{$null}})}}}})
      $e2=$null;$v=[Management.Automation.Language.Parser]::ParseFile('{psq(V22)}',[ref]$t,[ref]$e2)
      $mine=$a.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Import-ReviewedFunctions'}},$true)[0].Extent.Text
      $theirs=$v.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Import-ReviewedFunctions'}},$true)[0].Extent.Text
      Invoke-Case 'ast' {{[ordered]@{{errors=$e.Count;edition=$PSVersionTable.PSEdition;version=$PSVersionTable.PSVersion.Major;names=$names;top=$top;params=$params;import_identical=($mine -ceq $theirs)}}}}'''
    value = run_ps(tmp_path, body)['ast']['value']
    assert value['errors'] == 0 and value['edition'] == 'Desktop' and value['version'] == 5
    assert value['names'] == WRAPPER_FUNCTIONS
    assert value['top'] == ['Invoke-UpgradePreviewMain -Arguments ([ordered]@{Attempt=$Attempt;InstallRoot=$InstallRoot;Current=$Current;Candidate=$Candidate;'
                            'CandidateSha256=$CandidateSha256;Apply=[bool]$Apply}) -Workspace $PSScriptRoot']
    assert value['params'] == [{'name': 'Attempt', 'default': "'00000000000000000000000000000000'"}, {'name': 'InstallRoot', 'default': "''"},
                               {'name': 'Current', 'default': "'C:\\Program Files\\CoChem\\WardenCommissioning4.2.7-windows-20261007-r3-v1\\pipeline.json'"},
                               {'name': 'Candidate', 'default': "'C:\\Program Files\\CoChem\\WardenConfig4.2.7-windows-20261011-r5-v1\\pipeline.json'"},
                               {'name': 'CandidateSha256', 'default': "''"}, {'name': 'Apply', 'default': None}]
    assert value['import_identical'] is True and sha_file(V22) == V22_SHA256
    assert SCRIPT.read_bytes().isascii() and RUNNER.read_bytes().isascii() and Path(__file__).read_bytes().isascii()


def test_wrapper_pins_equal_the_files_on_disk_and_the_contract_strings():
    text = SCRIPT.read_text(encoding='ascii')
    assert f"$script:helperPin='{sha_file(RUNNER)}'" in text, 'the helper pin is the runner on disk'
    for path, needle in ((COPY_HELPER, "$copyHelper '"), (CHECK_R3, "'check-worker-native-status-r3.ps1') '"),
                         (REGISTER, "'register-stopped-warden-r3.ps1') '"), (INSPECTION, "'protected-code-inspection-v4.ps1') '"),
                         (V22, "'retarget-warden-r4.ps1') '"), (RETARGET_R5, "'retarget-warden-r5.ps1') '")):
        assert needle + sha_file(path) + "'" in text, path
    for needle in ("$script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'", "$script:taskTimeLimit='PT3M'", "$script:taskWaitSeconds=175",
                   "RegisterTaskDefinition($script:taskName,$definition,2,'SYSTEM',$null,5,$script:taskSddl)", "$script:namespaceDate='20261011'",
                   "$script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'",
                   "('UpgradePreview4.2.7-windows-'+$script:namespaceDate+'-r5-v1-'+$Attempt)", "'CoChem-4.2.7-UpgradePreview-'+$script:namespaceDate+'-r5-v1-'+$Attempt"):
        assert needle in text, needle
    assert text.count('.Run($null)') == 1 and text.count('RegisterTaskDefinition(') == 1 and text.count('NewTask(0)') == 1
    for forbidden in ('Stop-ScheduledTask', 'Disable-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask', 'Start-ScheduledTask', 'schtasks',
                      'Start-Process', 'Stop-Process', 'taskkill', 'Remove-Item', 'DeleteTask', 'Stop-Service', '.Stop(', '.Kill(', 'Invoke-Expression',
                      '.Enabled=$false', 'RunAs', 'Set-Content', 'Out-File', 'robocopy', 'job_board.db'):
        assert forbidden not in text, forbidden
    if (R4_ROOT / 'install-after.json').exists():
        after = json.loads((R4_ROOT / 'install-after.json').read_text(encoding='utf-8-sig'))
        assert f"$script:r4InstallPin='{sha_file(R4_ROOT / 'install-after.json')}'" in text
        assert f"$script:r4ManifestPin='{after['source_manifest_sha256']}'" in text and f"$script:configPin='{after['configuration_sha256']}'" in text
        assert f"$script:r4RevisionPin='{after['verification']['revision']['source_sha256']}'" in text
        assert f"$script:probePythonPin='{after['runtime_bindings']['base_python_sha256']}'" in text
        assert sha_file(R4_ROOT / 'pipeline.json') == m.CONFIG_SHA256


def _ps_functions(text):
    """Top-level 'function Name {' blocks of a house script (each closes with a '}' in column 0)."""
    functions, name, body = {}, None, []
    for line in text.splitlines():
        match = re.match(r'function ([A-Za-z0-9-]+) ?\{', line)
        if match and name is None:
            name, body = match.group(1), [line]
            if line.rstrip().endswith('}') and line.count('{') == line.count('}'):
                functions[name], name = line, None
            continue
        if name is not None:
            body.append(line)
            if line == '}':
                functions[name], name = '\n'.join(body), None
    return functions


def test_the_retarget_imports_are_closed_and_match_the_wrapper_list():
    text = SCRIPT.read_text(encoding='ascii')
    listed = re.search(r"'retarget-warden-r5\.ps1'\) '[a-f0-9]{64}' @\(([^)]*)\)", text).group(1)
    assert [item.strip().strip("'") for item in listed.split(',')] == RETARGET_IMPORTS
    retarget = _ps_functions(RETARGET_R5.read_text(encoding='utf-8'))
    assert set(RETARGET_IMPORTS) <= set(retarget)
    for name in RETARGET_IMPORTS:
        called = set(re.findall(r'\b([A-Z][a-z]+-[A-Za-z0-9]+)\b', retarget[name])) - {name}
        missing = {item for item in called if item in retarget and item not in RETARGET_IMPORTS and item not in PROVIDED_ELSEWHERE}
        assert not missing, (name, missing)
    v22 = _ps_functions(V22.read_text(encoding='utf-8'))
    for name in ('Test-ExactBool', 'Test-ExactInt'):
        assert retarget[name] == v22[name], 'the wrapper imports v2.2 ' + name + '; retarget-warden-r5 must use the same text'


def _script_assignments(body):
    """{name: assignment text} of every '$script:name=' statement in a function body (bracket and quote aware)."""
    result = {}
    for match in re.finditer(r'\$script:([A-Za-z_][A-Za-z0-9_]*)=', body):
        index, depth, quote = match.end(), 0, None
        while index < len(body):
            char = body[index]
            if quote:
                if char == quote:
                    quote = None
            elif char == "'":
                quote = char
            elif char in '([{':
                depth += 1
            elif char in ')]}':
                if depth == 0:
                    break
                depth -= 1
            elif char in ';\n' and depth == 0:
                break
            index += 1
        result.setdefault(match.group(1), body[match.end():index].strip())
    return result


def test_the_constants_the_retarget_imports_read_are_the_retarget_values():
    """Every $script: value the imported retarget functions read is set by Set-PreviewConstants with retarget's own text."""
    retarget = _ps_functions(RETARGET_R5.read_text(encoding='utf-8'))
    mine = _script_assignments(_ps_functions(SCRIPT.read_text(encoding='ascii'))['Set-PreviewConstants'])
    theirs = _script_assignments(retarget['Set-RetargetConstants'])
    used = set()
    for name in RETARGET_IMPORTS:
        used |= set(re.findall(r'\$script:([A-Za-z_][A-Za-z0-9_]*)', retarget[name]))
    assert used and used <= set(mine), sorted(used - set(mine))
    for name in sorted(used):
        assert name in theirs and mine[name] == theirs[name], (name, mine.get(name), theirs.get(name))
    assert mine['r5SourceManifestPin'] == "'" + sha_file(ROOT / 'stopped-runtime-r5-source-manifest.json') + "'", 'the reviewed freeze manifest on disk'


def test_import_by_hash_refuses_a_changed_source_and_a_tampered_helper_holds_the_plan(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / m.HELPER_NAME).write_bytes(RUNNER.read_bytes() + b'# tampered\n')
    body = f'''Invoke-Case 'wrong_hash' {{@(Import-ReviewedFunctions '{psq(V22)}' ('0'*64) @('Test-ExactBool'))}}
      Invoke-Case 'right_hash' {{@(Import-ReviewedFunctions '{psq(V22)}' '{V22_SHA256}' @('Test-ExactBool')).Count}}
      Invoke-Case 'missing_name' {{@(Import-ReviewedFunctions '{psq(V22)}' '{V22_SHA256}' @('No-SuchFunction'))}}
      function Resolve-R5Install {{param($r) [ordered]@{{root='R';python='P';install_after_path='A';install_after_sha256=('1'*64);venv_python_sha256=('2'*64);source_manifest_sha256=('3'*64);revision_sha256=('4'*64);reviewed_repairs=@('x')}}}}
      function Assert-CurrentConfig {{param($p) [ordered]@{{path=$p;sha256=$script:configPin;length=1}}}}
      function Resolve-Candidate {{param($p,$s) [ordered]@{{path=$p;sha256=('e'*64);length=1;mode='GEMINI_CONTRACT'}}}}
      function Get-ProviderDigests {{param($p,$s) $d=[Collections.Generic.SortedDictionary[string,string]]::new([StringComparer]::Ordinal);,$d}}
      $folder=[pscustomobject]@{{}};$folder|Add-Member ScriptMethod GetTask {{param($n) throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}}
      $request=[ordered]@{{attempt='{ATTEMPT}';install_root='';current='C';candidate='D';candidate_sha256=('e'*64);apply=$false}}
      Set-PreviewConstants '{ATTEMPT}' '{psq(workspace)}'
      Invoke-Case 'tampered' {{$p=Get-PreviewPlan $request $folder ([pscustomobject]@{{admin=$false;name='AETHERDESK\\ansac'}});[ordered]@{{holds=@($p.holds);verified=$p.document.helper_verified}}}}
      Set-PreviewConstants '{ATTEMPT}' '{psq(ROOT)}'
      Invoke-Case 'reviewed' {{$p=Get-PreviewPlan $request $folder ([pscustomobject]@{{admin=$false;name='AETHERDESK\\ansac'}});[ordered]@{{holds=@($p.holds);verified=$p.document.helper_verified;length=$p.source_length}}}}'''
    cases = run_ps(tmp_path, body)
    assert cases['wrong_hash']['ok'] is False and 'Reviewed function source changed' in cases['wrong_hash']['error']
    assert cases['right_hash']['value'] == 1
    assert cases['missing_name']['ok'] is False and 'Expected exactly one reviewed definition' in cases['missing_name']['error']
    tampered = cases['tampered']['value']
    assert tampered['verified'] is False and any('differs from its pin' in hold for hold in tampered['holds'])
    assert cases['reviewed']['value']['verified'] is True and cases['reviewed']['value']['holds'] == [] and cases['reviewed']['value']['length'] == RUNNER.stat().st_size


PARAMETER_CASES = {
    'plan_default': ("@{Attempt=('0'*32);InstallRoot='';Current='C';Candidate='D';CandidateSha256='';Apply=$false}", None),
    'apply_zero_attempt': ("@{Attempt=('0'*32);InstallRoot='';Current='C';Candidate='D';CandidateSha256=('e'*64);Apply=$true}", 'all-zero preview attempt'),
    'upper_attempt': ("@{Attempt=('C'*32);InstallRoot='';Current='C';Candidate='D';CandidateSha256='';Apply=$false}", 'lowercase 32-hex -Attempt'),
    'bad_candidate_sha': ("@{Attempt=('c'*32);InstallRoot='';Current='C';Candidate='D';CandidateSha256=('E'*64);Apply=$false}", 'lowercase sha256 from the staging receipt'),
    'apply_without_candidate_sha': ("@{Attempt=('c'*32);InstallRoot='';Current='C';Candidate='D';CandidateSha256='';Apply=$true}", 'requires -CandidateSha256'),
    'install_root_r4': ("@{Attempt=('c'*32);InstallRoot='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261009-r4';Current='C';Candidate='D';CandidateSha256='';Apply=$false}", '-InstallRoot must be'),
    'install_root_ok': ("@{Attempt=('c'*32);InstallRoot='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261011-r5';Current='C';Candidate='D';CandidateSha256=('e'*64);Apply=$true}", None),
}
IDENTITY_CASES = {'owner_admin': ('$true', 'AETHERDESK\\ansac', '$true', None), 'not_admin': ('$true', 'AETHERDESK\\ansac', '$false', 'requires the owner'),
                  'other_user': ('$true', 'AETHERDESK\\other', '$true', 'requires the owner'), 'plan_not_admin': ('$false', 'AETHERDESK\\ansac', '$false', None)}


def test_parameters_and_apply_identity_refuse_before_anything_is_read(tmp_path):
    lines = [f"Invoke-Case 'p_{name}' {{Assert-PreviewParameters ([ordered]{args})}}" for name, (args, _) in PARAMETER_CASES.items()]
    lines += [f"Invoke-Case 'i_{name}' {{Assert-PreviewApplyIdentity {apply} ([pscustomobject]@{{admin={admin};name='{who}'}});'ok'}}"
              for name, (apply, who, admin, _) in IDENTITY_CASES.items()]
    cases = run_ps(tmp_path, '\n'.join(lines))
    for name, (_, expected) in PARAMETER_CASES.items():
        case = cases['p_' + name]
        assert case['ok'] is (expected is None), case
        if expected:
            assert expected in case['error'] and 'Nothing was changed' in case['error']
    for name, (_, _, _, expected) in IDENTITY_CASES.items():
        case = cases['i_' + name]
        assert case['ok'] is (expected is None) and (expected is None or expected in case['error']), case


def split_windows(command_line):
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    try:
        return [argv[index] for index in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


def test_task_definition_fields_registration_check_and_argument_round_trip(tmp_path):
    body = r'''function New-FixtureDefinition {
        $actions=[pscustomobject]@{Count=0;list=[Collections.ArrayList]::new()}
        $actions|Add-Member ScriptMethod Create {param($t) $a=[pscustomobject]@{Type=$t;Path=$null;Arguments=$null;WorkingDirectory=$null};$null=$this.list.Add($a);$this.Count=$this.list.Count;$a}
        $actions|Add-Member ScriptMethod Item {param($i) $this.list[$i-1]}
        [pscustomobject]@{RegistrationInfo=[pscustomobject]@{Description=$null};Principal=[pscustomobject]@{UserId=$null;LogonType=$null;RunLevel=$null};
          Settings=[pscustomobject]@{Enabled=$null;AllowDemandStart=$null;MultipleInstances=$null;ExecutionTimeLimit=$null;RestartCount=$null};Triggers=[pscustomobject]@{Count=0};Actions=$actions}}
      $scheduler=[pscustomobject]@{};$scheduler|Add-Member ScriptMethod NewTask {param($f) New-FixtureDefinition}
      $ctx=[ordered]@{install_root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5';python='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\.venv\Scripts\python.exe';
        install_after_sha256=('1'*64);venv_python_sha256=('2'*64);current_path='C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json';
        current_sha256=$script:configPin;proposed_path='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json';proposed_sha256=('3'*64);mode='enabled'}
      $dest=Join-Path $script:targetRoot $script:helperName;$nonce='__NONCE__'
      function New-FixtureTask {param([hashtable]$Change=@{})
        $d=New-PreviewTaskDefinition $scheduler $dest $nonce $ctx
        foreach($k in @($Change.Keys)){switch($k){'Trigger'{$d.Triggers.Count=1}'Limit'{$d.Settings.ExecutionTimeLimit='PT72H'}'Path'{$d.Actions.Item(1).Path='C:\Python314\python.exe'}'Args'{$d.Actions.Item(1).Arguments+=' --extra'}'User'{$d.Principal.UserId='AETHERDESK\ansac'}}}
        $sddl='O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)';if($Change.ContainsKey('Sddl')){$sddl=$Change.Sddl}
        $t=[pscustomobject]@{Enabled=$true;State=3;Definition=$d;Sddl=$sddl}
        $t|Add-Member ScriptMethod GetInstances {param($n)[pscustomobject]@{Count=0}};$t|Add-Member ScriptMethod GetSecurityDescriptor {param($n)$this.Sddl};$t}
      Invoke-Case 'definition' {$d=New-PreviewTaskDefinition $scheduler $dest $nonce $ctx;$a=$d.Actions.Item(1)
        [ordered]@{user=$d.Principal.UserId;logon=$d.Principal.LogonType;run_level=$d.Principal.RunLevel;enabled=$d.Settings.Enabled;demand=$d.Settings.AllowDemandStart;
          instances=$d.Settings.MultipleInstances;limit=$d.Settings.ExecutionTimeLimit;restart=$d.Settings.RestartCount;triggers=$d.Triggers.Count;actions=$d.Actions.Count;
          type=$a.Type;path=$a.Path;arguments=$a.Arguments;wd=$a.WorkingDirectory;description=$d.RegistrationInfo.Description}}
      Invoke-Case 'ok' {Assert-PreviewTaskRegistration (New-FixtureTask) $dest $nonce $ctx;'ok'}
      foreach($c in @('Trigger','Limit','Path','Args','User')){Invoke-Case ('bad_'+$c) {Assert-PreviewTaskRegistration (New-FixtureTask @{$c=1}) $dest $nonce $ctx}}
      Invoke-Case 'bad_Sddl' {Assert-PreviewTaskRegistration (New-FixtureTask @{Sddl='O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)'}) $dest $nonce $ctx}
      Invoke-Case 'plan_arguments' {Get-PreviewTaskArguments $dest '<nonce>' $ctx}'''.replace('__NONCE__', NONCE)
    cases = run_ps(tmp_path, body)
    d = cases['definition']['value']
    root = COCHEM / ROOT_NAME
    python = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\.venv\Scripts\python.exe'
    assert (d['user'], d['logon'], d['run_level'], d['enabled'], d['demand'], d['instances'], d['limit'], d['restart'], d['triggers'], d['actions'], d['type']) == \
        ('SYSTEM', 5, 1, True, True, 2, 'PT3M', 0, 0, 1, 0)
    assert d['path'] == python and d['wd'] == str(root) and d['description'].isascii()
    assert cases['ok']['ok'] is True, cases['ok']
    for name in ('bad_Trigger', 'bad_Limit', 'bad_User'):
        assert cases[name]['ok'] is False and 'exact idle, trigger-free, bounded SYSTEM definition' in cases[name]['error'], name
    for name in ('bad_Path', 'bad_Args'):
        assert cases[name]['ok'] is False and 'registered preview action differs' in cases[name]['error'], name
    assert cases['bad_Sddl']['ok'] is False and 'DACL' in cases['bad_Sddl']['error'], cases['bad_Sddl']
    # The registered action, split exactly as Windows splits a command line, is what the helper's own parser accepts.
    argv = split_windows('"' + python + '" ' + d['arguments'])
    assert argv[:4] == [python, '-I', '-B', str(root / m.HELPER_NAME)]
    settings = m.settings_from_args(m.build_parser().parse_args(argv[4:]))
    assert settings == m.Settings(attempt=ATTEMPT, nonce=NONCE, install_root=Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5'),
                                  install_after_sha256='1' * 64, venv_python_sha256='2' * 64,
                                  current=COCHEM / 'WardenCommissioning4.2.7-windows-20261007-r3-v1' / 'pipeline.json', current_sha256=m.CONFIG_SHA256,
                                  proposed=COCHEM / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json', proposed_sha256='3' * 64,
                                  mode='enabled', output=root / 'upgrade-preview.json')
    assert '--nonce <nonce>' in cases['plan_arguments']['value']


def gate_contexts():
    """Every gate case, the clean previews and a few edge shapes; enabled cases name the pair of bound files whose
    per-provider digests the gate compares (B-F5)."""
    current = {'path': 'C:\\Program Files\\CoChem\\WardenCommissioning4.2.7-windows-20261007-r3-v1\\pipeline.json', 'sha256': m.CONFIG_SHA256}
    proposed = {'path': 'C:\\Program Files\\CoChem\\WardenConfig4.2.7-windows-20261011-r5-v1\\pipeline.json', 'sha256': '9' * 64}
    cases = {}
    for name, (mode, changes, mutate, _) in GATE_CASES.items():
        preview = clean_preview(current, proposed, changes)
        if mutate:
            mutate(preview)
        cases[name] = (mode, preview, 'gemini_only' if mode == 'enabled' else None)
    cases['clean_held'] = ('held', clean_preview(current, proposed), None)
    cases['clean_enabled'] = ('enabled', clean_preview(current, proposed, ('providers',)), 'gemini_only')
    cases['same_file_no_swap'] = ('held', clean_preview(current, {**proposed, 'path': current['path']}), None)
    cases['not_an_object'] = ('held', [1, 2], None)
    preview = clean_preview(current, proposed)
    preview['identities'][0]['key'] = 3
    cases['identity_key_not_string'] = ('held', preview, None)
    preview = clean_preview(current, proposed, ('providers',))
    preview['protected_paths'][0]['before'] = 7
    cases['configuration_before_not_string'] = ('enabled', preview, 'gemini_only')
    for case in PROVIDER_CASES:
        cases['providers_' + case] = ('enabled', clean_preview(current, proposed, ('providers',)), case)
    cases['providers_digests_missing'] = ('enabled', clean_preview(current, proposed, ('providers',)), 'no_digests')
    cases['providers_claude_and_workers'] = ('enabled', clean_preview(current, proposed, ('providers', 'workers')), 'claude_changed_too')
    return current, proposed, cases


def test_python_and_powershell_gates_agree_on_every_case(tmp_path):
    current, proposed, cases = gate_contexts()
    folder = tmp_path / 'previews'
    folder.mkdir()
    configs = tmp_path / 'configs'
    configs.mkdir()
    (configs / 'current.json').write_bytes(COMMISSIONED)
    lines = [f"$ctxBase=[ordered]@{{current_path='{psq(current['path'])}';current_sha256='{current['sha256']}';proposed_path='{psq(proposed['path'])}';proposed_sha256='{proposed['sha256']}'}}",
             "Invoke-Case 'lists' {[ordered]@{reasons=$script:gateReasons;phases=$script:failurePhases;failures=$script:failureReasons;allowed=$script:allowedConfigurationKeys;providers=$script:allowedChangedProviders}}",
             "$contexts=@{};$contexts['none']=$ctxBase;$contexts['no_digests']=$ctxBase"]
    bound = {'none': (current, proposed), 'no_digests': (current, proposed)}
    for pair in PROVIDER_CASES:
        data = provider_case_bytes(pair)
        (configs / (pair + '.json')).write_bytes(data)
        bound[pair] = ({**current, 'providers_sha256': m.provider_digests(COMMISSIONED_DOC)}, {**proposed, 'providers_sha256': m.provider_digests(json.loads(data))})
        lines.append(f"$c=[ordered]@{{}};foreach($k in $ctxBase.Keys){{$c[$k]=$ctxBase[$k]}};"
                     f"$c['current_providers_sha256']=(Get-ProviderDigests '{psq(configs / 'current.json')}' '{sha(COMMISSIONED)}');"
                     f"$c['proposed_providers_sha256']=(Get-ProviderDigests '{psq(configs / (pair + '.json'))}' '{sha(data)}');$contexts['{pair}']=$c")
    for name, (mode, value, pair) in cases.items():
        path = folder / (name + '.json')
        path.write_bytes(encode(value))
        lines.append(f"Invoke-Case '{name}' {{$p=Get-Content -Raw -Encoding UTF8 -LiteralPath '{psq(path)}'|ConvertFrom-Json;$g=Get-PreviewGate $p '{mode}' $contexts['{pair or 'none'}'];"
                     "[ordered]@{passed=$g.passed;reasons=@($g.reasons);identities=@($g.identities_changed);paths=@($g.protected_paths_changed);"
                     "swap=$g.configuration_path_swap_accepted;keys=@($g.configuration_change_keys);schema_count=$g.schema_change_count;exists=$g.database_exists;"
                     "workflows=$g.workflows_captured;providers=@($g.providers_changed)}}")
    ps_cases = run_ps(tmp_path, '\n'.join(lines))
    lists = ps_cases['lists']['value']
    assert lists['reasons'] == list(m.REASONS) and lists['phases'] == list(m.FAILURE_PHASES) and lists['failures'] == list(m.FAILURE_REASONS)
    assert lists['allowed'] == list(m.ALLOWED_CONFIGURATION_KEYS) and lists['providers'] == list(m.ALLOWED_CHANGED_PROVIDERS)
    for name, (mode, value, pair) in cases.items():
        bound_current, bound_proposed = bound[pair or 'none']
        expected = m.evaluate_gate(value, mode, bound_current, bound_proposed)
        got = ps_cases[name]
        assert got['ok'], (name, got)
        s = expected['summary']
        assert got['value'] == {'passed': expected['passed'], 'reasons': expected['reasons'], 'identities': s['identities_changed'],
                                'paths': s['protected_paths_changed'], 'swap': s['configuration_path_swap_accepted'], 'keys': s['configuration_change_keys'],
                                'schema_count': s['schema_change_count'], 'exists': s['database_exists'], 'workflows': s['workflows_captured'],
                                'providers': s['providers_changed']}, name
    assert m.evaluate_gate(cases['clean_held'][1], 'held', current, proposed)['passed'] is True
    assert m.evaluate_gate(cases['same_file_no_swap'][1], 'held', current, {**proposed, 'path': current['path']})['passed'] is True
    gemini_only = m.evaluate_gate(cases['providers_gemini_only'][1], 'enabled', *bound['gemini_only'])
    assert gemini_only['passed'] is True and gemini_only['summary']['providers_changed'] == ['gemini']
    claude = m.evaluate_gate(cases['providers_claude_changed_too'][1], 'enabled', *bound['claude_changed_too'])
    assert claude['reasons'] == ['PROVIDERS_CHANGED_OUTSIDE_GEMINI']
    assert m.evaluate_gate(cases['providers_digests_missing'][1], 'enabled', current, proposed)['reasons'] == ['PROVIDER_DIGESTS_MALFORMED']


def test_wrapper_provider_digests_are_read_from_the_bound_file_by_sha256(tmp_path):
    folder = tmp_path / 'cfg'
    folder.mkdir()
    (folder / 'enabled.json').write_bytes(ENABLED)
    (folder / 'no-providers.json').write_bytes(b'{"workers": {}}')
    body = f'''Invoke-Case 'enabled' {{$d=Get-ProviderDigests '{psq(folder / 'enabled.json')}' '{sha(ENABLED)}';[ordered]@{{type=$d.GetType().Name;names=@($d.Keys);valid=(Test-ProviderDigestMap $d)}}}}
      Invoke-Case 'none' {{$null -eq (Get-ProviderDigests '{psq(folder / 'no-providers.json')}' '')}}
      Invoke-Case 'sha' {{Get-ProviderDigests '{psq(folder / 'enabled.json')}' ('0'*64)}}
      Invoke-Case 'hashtable_map' {{Test-ProviderDigestMap @{{gemini=('a'*64)}}}}
      Invoke-Case 'upper_digest' {{$d=[Collections.Generic.SortedDictionary[string,string]]::new([StringComparer]::Ordinal);$d['gemini']=('A'*64);Test-ProviderDigestMap $d}}
      Invoke-Case 'ignore_case_map' {{$d=[Collections.Generic.SortedDictionary[string,string]]::new([StringComparer]::OrdinalIgnoreCase);Test-ProviderDigestMap $d}}'''
    cases = run_ps(tmp_path, body)
    assert cases['enabled']['value'] == {'type': 'SortedDictionary`2', 'names': ['claude', 'gemini'], 'valid': True}, cases['enabled']
    assert cases['none']['value'] is True
    assert cases['sha']['ok'] is False and 'Source digest changed' in cases['sha']['error']
    assert [cases[name]['value'] for name in ('hashtable_map', 'upper_digest', 'ignore_case_map')] == [False, False, False]


# ----------------------------------------------------------------------------------------------- wrapper: receipts and the apply path

@pytest.fixture(scope='module')
def produced(tmp_path_factory):
    base = tmp_path_factory.mktemp('produced')
    runs = {}
    for name, mode, kind in (('pass_held', 'held', 'pass'), ('pass_enabled', 'enabled', 'pass'), ('gate_fail', 'held', 'gate'),
                             ('preview_failed', 'held', 'nonzero'), ('install_failed', 'held', 'install')):
        fx = Fixture(base / name, mode, install_mutate=(_set(['mode'], 'PARTIAL') if kind == 'install' else None))
        changes = ('providers',) if mode == 'enabled' else ()
        preview = clean_preview(fx.current_info, fx.proposed_info, changes)
        if kind == 'gate':
            preview['database']['schema_changes'] = [{'object': 'table:obsolete_extra', 'action': 'preserve_unmanaged_object'}]
        launcher = FakeLauncher(stdout=b'', stderr=b'boom\n', exit_code=1) if kind == 'nonzero' else FakeLauncher(stdout=encode(preview))
        result = run_fixture(fx, launcher=launcher)
        runs[name] = SimpleNamespace(fx=fx, code=result.code, receipt=result.receipt)
    return runs


RECEIPT_TAMPER = {
    'helper_sha': "$r.helper_sha256=('0'*64)", 'nonce_differs': "$nonce=('e'*32)", 'install_after': "$r.install_after_sha256=('0'*64)",
    'system_sid': "$r.system_sid='S-1-5-32-544'", 'gate_reasons_edited': "$r.gate.reasons=@('READ_ONLY_NOT_TRUE')", 'gate_passed_edited': "$r.gate.passed=$false",
    'status_vs_result': "$task=[pscustomobject]@{LastTaskResult=3}", 'model_claim': "$r.native_models_executed=$true",
    'command_edited': "$r.command[1]='-E'", 'child_exit': "$r.child.exit_code=1", 'mode_differs': "$ctx.mode='enabled'",
    'unknown_status': "$r.status='UPGRADE_PREVIEW_MAYBE'",
}


def test_wrapper_receipt_validation_accepts_runner_receipts_and_refuses_tampering(produced, tmp_path):
    ok, enabled, gate, failed, install = (produced[k] for k in ('pass_held', 'pass_enabled', 'gate_fail', 'preview_failed', 'install_failed'))
    tampered = tmp_path / 'tampered'
    shutil.copytree(ok.fx.root, tampered)
    with open(tampered / 'upgrade-preview.json', 'ab') as stream:
        stream.write(b' ')
    extra_held = tmp_path / 'extra_held'
    shutil.copytree(ok.fx.root, extra_held)
    (extra_held / 'upgrade-preview-held.json').write_bytes(b'{}')
    held_tampered = tmp_path / 'held_tampered'
    shutil.copytree(gate.fx.root, held_tampered)
    with open(held_tampered / 'upgrade-preview-held.json', 'ab') as stream:
        stream.write(b' ')

    def case(name, run, root=None, result=0, tamper=''):
        root = root or run.fx.root
        return (f"{run.fx.ps_context()}$task=[pscustomobject]@{{LastTaskResult={result}}};$nonce='{NONCE}'\n"
                f"$r=Get-Content -Raw -LiteralPath '{psq(root / 'upgrade-preview-receipt.json')}'|ConvertFrom-Json;{tamper}\n"
                f"Invoke-Case '{name}' {{$v=Assert-PreviewReceipt $r $task $ctx $nonce '{psq(root)}';"
                "$reasons=$null;if($null -ne $v.gate){$reasons=@($v.gate.reasons)};[ordered]@{decision=$v.decision;"
                "passed=$(if($null -ne $v.gate){$v.gate.passed}else{$null});reasons=$reasons;"
                "failure=$v.failure;swap=$(if($null -ne $v.gate){$v.gate.configuration_path_swap_accepted}else{$null})}}")
    lines = [case('ok', ok), case('enabled', enabled), case('gate', gate, result=3), case('failed', failed, result=4),
             case('install_failed', install, result=4), case('preview_tampered', ok, root=tampered), case('extra_held', ok, root=extra_held),
             case('held_tampered', gate, root=held_tampered, result=3)]
    lines += [case('t_' + name, ok, tamper=tamper) for name, tamper in RECEIPT_TAMPER.items()]
    cases = run_ps(tmp_path, '\n'.join(lines))
    assert cases['ok']['value'] == {'decision': 'PASSED', 'passed': True, 'reasons': [], 'failure': None, 'swap': True}
    assert cases['enabled']['value']['decision'] == 'PASSED'
    assert cases['gate']['value'] == {'decision': 'GATE_FAILED', 'passed': False, 'reasons': ['SCHEMA_CHANGES_PRESENT'], 'failure': None, 'swap': True}
    assert cases['failed']['value']['decision'] == 'FAILED' and cases['failed']['value']['failure'] == {'phase': 'preview_launch', 'reason': 'PREVIEW_EXIT_NONZERO', 'error_type': 'PreviewRefusal'}
    assert cases['install_failed']['value']['failure']['reason'] == 'INSTALL_BINDING_DIFFERS'
    expected = {'preview_tampered': 'Source digest changed', 'extra_held': 'must not carry a held record', 'held_tampered': 'Source digest changed',
                't_helper_sha': 'identity/runtime binding', 't_nonce_differs': 'identity/runtime binding', 't_install_after': 'runtime/configuration binding',
                't_system_sid': 'identity/runtime binding', 't_gate_reasons_edited': 'contradicts the retained preview',
                't_gate_passed_edited': 'contradicts the retained preview', 't_status_vs_result': 'contradicts the preview receipt status',
                't_model_claim': 'Out-of-scope claim', 't_command_edited': 'child command differs', 't_child_exit': 'did not exit 0',
                't_mode_differs': 'identity/runtime binding', 't_unknown_status': 'not a known terminal status'}
    for name, needle in expected.items():
        assert cases[name]['ok'] is False and needle in cases[name]['error'], (name, cases[name])


APPLY_FIXTURE = r'''
  $script:registered=@();$script:runs=0;$script:task=$null;$script:newTasks=0
  function New-PrivateDirectory {param($Path) if(Test-Path -LiteralPath $Path){throw ('Private directory already exists; preserve it: '+$Path)};$null=[IO.Directory]::CreateDirectory($Path)}
  function Copy-VerifiedPayload {param($File) if((Get-FileHash -LiteralPath $File.source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $File.sha256){throw 'Source digest changed'};[IO.File]::Copy($File.source,$File.destination)}
  function Assert-CodeTreeOnce {param($Path) $script:codeTrees+=$Path;7}
  function New-PreviewNonce {'__NONCE__'}
  function Start-Sleep {param($Seconds,$Milliseconds)[Threading.Thread]::Sleep(5)}
  function New-FixtureScheduler {
    $scheduler=[pscustomobject]@{}
    $scheduler|Add-Member ScriptMethod NewTask {param($f)
      $script:newTasks++
      $actions=[pscustomobject]@{Count=0;list=[Collections.ArrayList]::new()}
      $actions|Add-Member ScriptMethod Create {param($t) $a=[pscustomobject]@{Type=$t;Path=$null;Arguments=$null;WorkingDirectory=$null};$null=$this.list.Add($a);$this.Count=$this.list.Count;$a}
      $actions|Add-Member ScriptMethod Item {param($i) $this.list[$i-1]}
      [pscustomobject]@{RegistrationInfo=[pscustomobject]@{Description=$null};Principal=[pscustomobject]@{UserId=$null;LogonType=$null;RunLevel=$null};
        Settings=[pscustomobject]@{Enabled=$null;AllowDemandStart=$null;MultipleInstances=$null;ExecutionTimeLimit=$null;RestartCount=$null};Triggers=[pscustomobject]@{Count=0};Actions=$actions}}
    $scheduler}
  function New-FixtureFolder {
    $folder=[pscustomobject]@{}
    $folder|Add-Member ScriptMethod GetTask {param($name) if(($null -ne $script:task -or $script:fx.TaskExists) -and $name -ceq $script:taskName){return $script:task};throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}
    $folder|Add-Member ScriptMethod RegisterTaskDefinition {param($name,$def,$flags,$user,$pw,$logon,$sddl)
      $script:registered+=[pscustomobject]@{name=$name;flags=$flags;user=$user;logon=$logon;sddl=$sddl;arguments=$def.Actions.Item(1).Arguments;path=$def.Actions.Item(1).Path;limit=$def.Settings.ExecutionTimeLimit}
      $script:task=[pscustomobject]@{Enabled=$def.Settings.Enabled;State=3;LastTaskResult=267011;Definition=$def;Xml='<Task>fixture</Task>';Instances=0}
      $script:task|Add-Member ScriptMethod GetInstances {param($n)[pscustomobject]@{Count=$script:task.Instances}}
      $script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($n)$script:fx.Sddl}
      $script:task|Add-Member ScriptMethod Run {param($a)
        $script:runs++
        if($script:fx.CopyReceipt){foreach($f in Get-ChildItem -LiteralPath $script:fixtureSource -File){[IO.File]::Copy($f.FullName,(Join-Path $script:targetRoot $f.Name))}}
        $script:task.LastTaskResult=$script:fx.LastTaskResult;$i=[pscustomobject]@{State=4};$i|Add-Member ScriptMethod Refresh {if($script:fx.RefreshEnds){$this.State=3}};$i}
      $script:task}
    $folder}
  function Invoke-ApplyCase {param([string]$Name,[string]$Source,[hashtable]$Fx,[switch]$PreCreate,[int]$Wait=175)
    Set-PreviewConstants '__ATTEMPT__' '__WORKSPACE__';$script:taskWaitSeconds=$Wait;$script:configPin=$ctx.current_sha256
    $script:targetRoot=Join-Path '__TMPROOT__' $Name
    if($script:targetRoot -like 'C:\Program Files*'){throw 'fixture roots must be temporary'}
    $script:registered=@();$script:runs=0;$script:task=$null;$script:fixtureSource=$Source;$script:codeTrees=@();$script:newTasks=0
    $script:fx=@{Sddl='O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)';LastTaskResult=0;CopyReceipt=$true;RefreshEnds=$true;TaskExists=$false};foreach($k in $Fx.Keys){$script:fx[$k]=$Fx[$k]}
    if($PreCreate){$null=[IO.Directory]::CreateDirectory($script:targetRoot)}
    $result=[ordered]@{ok=$true;error=$null;summary=$null}
    try{$s=Invoke-UpgradePreview (New-FixtureScheduler) (New-FixtureFolder) $ctx ((Get-Item -LiteralPath $script:helperSource).Length) 6>$null
        $result.summary=[ordered]@{status=$s.status;decision=$s.decision;passed=$s.gate.passed;reasons=@($s.gate.reasons);series_stop=$s.series_stop;message=$s.message;
          swap=$s.configuration_path_swap_accepted;keys=@($s.configuration_change_keys);prerequisites=@($s.rollback_prerequisites|ForEach-Object {$_.id});mode=$s.config_mode;
          outcome=(Write-PreviewOutcome $s|ConvertFrom-Json).decision}}
    catch{$result.ok=$false;$result.error=$_.Exception.Message}
    foreach($s in $held){$s.Dispose()};$held.Clear()
    $files=@();if(Test-Path -LiteralPath $script:targetRoot){$files=@(Get-ChildItem -LiteralPath $script:targetRoot -File|ForEach-Object {$_.Name}|Sort-Object)}
    $heldRecord=$null;$heldPath=Join-Path $script:targetRoot 'preview-held.json';if(Test-Path -LiteralPath $heldPath){$heldRecord=Get-Content -Raw -LiteralPath $heldPath|ConvertFrom-Json}
    $result.files=$files;$result.registered=@($script:registered);$result.runs=$script:runs;$result.held=$heldRecord;$result.code_trees=@($script:codeTrees);$result.new_tasks=$script:newTasks
    'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=$result}|ConvertTo-Json -Depth 10 -Compress)}
'''


def test_wrapper_apply_path_is_driven_with_fixtures(produced, tmp_path):
    ok, gate, failed = produced['pass_held'], produced['gate_fail'], produced['preview_failed']
    fixture = APPLY_FIXTURE.replace('__NONCE__', NONCE).replace('__ATTEMPT__', ATTEMPT).replace('__WORKSPACE__', psq(ROOT)).replace('__TMPROOT__', psq(tmp_path / 'apply'))
    (tmp_path / 'apply').mkdir()
    calls = [ok.fx.ps_context() + fixture,
             f"Invoke-ApplyCase 'pass' '{psq(ok.fx.root)}' @{{}}",
             f"Invoke-ApplyCase 'no_receipt' '{psq(ok.fx.root)}' @{{CopyReceipt=$false;LastTaskResult=5}}",
             f"Invoke-ApplyCase 'acl' '{psq(ok.fx.root)}' @{{Sddl='O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)'}}",
             f"Invoke-ApplyCase 'root_exists' '{psq(ok.fx.root)}' @{{}} -PreCreate",
             f"Invoke-ApplyCase 'task_exists' '{psq(ok.fx.root)}' @{{TaskExists=$true}}",
             f"Invoke-ApplyCase 'wait_timeout' '{psq(ok.fx.root)}' @{{RefreshEnds=$false;CopyReceipt=$false}} -Wait 1",
             f"Invoke-ApplyCase 'wrong_result' '{psq(ok.fx.root)}' @{{LastTaskResult=4}}",
             gate.fx.ps_context(), f"Invoke-ApplyCase 'gate_fail' '{psq(gate.fx.root)}' @{{LastTaskResult=3}}",
             failed.fx.ps_context(), f"Invoke-ApplyCase 'preview_failed' '{psq(failed.fx.root)}' @{{LastTaskResult=4}}"]
    cases = run_ps(tmp_path, '\n'.join(calls))
    v = {name: case['value'] for name, case in cases.items()}
    target = tmp_path / 'apply' / 'pass'
    p = v['pass']
    assert p['ok'], p
    assert p['summary']['decision'] == 'PASSED' and p['summary']['passed'] is True and p['summary']['series_stop'] is False and p['summary']['outcome'] == 'PASSED'
    assert p['summary']['swap'] is True and p['summary']['keys'] == [] and p['summary']['mode'] == 'held'
    assert p['summary']['prerequisites'] == ['quiesced_workers', 'job_board_online_backup'] and p['summary']['message'].startswith('S10 upgrade preview gate passed')
    expected_args = (f'-I -B "{target / m.HELPER_NAME}" --attempt {ATTEMPT} --nonce {NONCE} --install-root "{ok.fx.install}" '
                     f'--install-after-sha256 {ok.fx.settings.install_after_sha256} --venv-python-sha256 {ok.fx.settings.venv_python_sha256} '
                     f'--current "{ok.fx.current_info["path"]}" --current-sha256 {ok.fx.commissioned} --proposed "{ok.fx.proposed_info["path"]}" '
                     f'--proposed-sha256 {ok.fx.proposed_info["sha256"]} --mode held --output "{target / "upgrade-preview.json"}"')
    assert p['registered'] == [{'name': f'CoChem-4.2.7-UpgradePreview-20261011-r5-v1-{ATTEMPT}', 'flags': 2, 'user': 'SYSTEM', 'logon': 5,
                                'sddl': SDDL, 'arguments': expected_args, 'path': str(ok.fx.python), 'limit': 'PT3M'}]
    assert p['runs'] == 1 and p['new_tasks'] == 1 and p['held'] is None and len(p['code_trees']) == 2
    assert sorted(p['files']) == sorted(['run_upgrade_preview_r5_v1.py', 'preview-intent.json', 'preview-task.xml', 'preview-summary.json',
                                         'upgrade-preview-receipt.json', 'upgrade-preview.json', 'upgrade-preview.stderr.txt'])
    assert (target / m.HELPER_NAME).read_bytes() == RUNNER.read_bytes()
    intent = json.loads((target / 'preview-intent.json').read_text(encoding='utf-8'))
    assert intent['schema'] == 'cochem-upgrade-preview-r5-intent/1' and intent['retry'] is False and intent['task_action']['arguments'] == expected_args
    summary = json.loads((target / 'preview-summary.json').read_text(encoding='utf-8'))
    assert summary['schema'] == 'cochem-upgrade-preview-r5-result/1' and summary['install_after_sha256'] == ok.fx.settings.install_after_sha256
    g = v['gate_fail']
    assert g['ok'] is False and g['error'].startswith('SERIES-STOP (S10): the upgrade preview gate failed (SCHEMA_CHANGES_PRESENT)')
    assert 'R4-RESTORE' in g['error'] and 'waiver' in g['error']
    assert g['held']['phase'] == 'GATE' and g['held']['gate_reasons'] == ['SCHEMA_CHANGES_PRESENT'] and g['held']['automatic_retry_allowed'] is False
    assert 'preview-summary.json' in g['files'] and 'upgrade-preview-held.json' in g['files'] and g['runs'] == 1
    gate_summary = json.loads((tmp_path / 'apply' / 'gate_fail' / 'preview-summary.json').read_text(encoding='utf-8'))
    assert gate_summary['gate'] == {'passed': False, 'reasons': ['SCHEMA_CHANGES_PRESENT']} and gate_summary['series_stop'] is True
    assert gate_summary['identities_changed'] == [] and gate_summary['schema_change_count'] == 1 and gate_summary['decision'] == 'GATE_FAILED'
    f = v['preview_failed']
    assert f['ok'] is False and 'did not complete (PREVIEW_EXIT_NONZERO, phase preview_launch)' in f['error'] and f['held']['phase'] == 'GATE'
    assert f['held']['helper_failure']['reason'] == 'PREVIEW_EXIT_NONZERO'
    n = v['no_receipt']
    assert n['ok'] is False and 'left no receipt (LastTaskResult 5)' in n['error'] and n['held']['phase'] == 'RECEIPT' and n['runs'] == 1
    a = v['acl']
    assert a['ok'] is False and 'held at task registration' in a['error'] and a['runs'] == 0 and a['held']['task_registered'] is True and a['held']['run_requested'] is False
    for name in ('root_exists', 'task_exists'):
        assert v[name]['ok'] is False and 'held before any change' in v[name]['error'] and 'Nothing was changed' in v[name]['error']
        assert v[name]['registered'] == [] and v[name]['runs'] == 0 and v[name]['held'] is None and v[name]['new_tasks'] == 0
    assert v['root_exists']['files'] == []
    w = v['wait_timeout']
    assert w['ok'] is False and 'did not end cleanly' in w['error'] and w['held']['phase'] == 'WAIT' and w['runs'] == 1
    r = v['wrong_result']
    assert r['ok'] is False and 'contradicts the preview receipt status' in r['error'] and r['held']['phase'] == 'RECEIPT'


def make_r5_tree(base: Path, toolchain: Path) -> Path:
    """An installed r5 root that the imported retarget-warden-r5 Assert-R5InstalledBindings accepts."""
    root = base / 'Pipeline4.2.7-windows-20261011-r5'
    root.mkdir(parents=True)
    files = {}

    def put(relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[relative] = sha(data)
    put('pipeline.json', COMMISSIONED)
    put('.venv/pyvenv.cfg', b'home = toolchain\r\n')
    put('.venv/Scripts/python.exe', b'MZ fake venv launcher')
    pins = {}
    for relative in R5_REPAIRS:
        data = ('# reviewed ' + relative + '\r\n').encode('ascii')
        put('source/' + relative, data)
        put('.venv/Lib/site-packages/' + relative[4:], data)
        pins[relative] = sha(data)
    rows = [{'relative': relative, 'sha256': pins[relative], 'length': 1} for relative in R5_REPAIRS]
    rows += [{'relative': f'src/cochem_pipeline/unchanged_{index}.py', 'sha256': '%064x' % index, 'length': 1} for index in range(166 - len(rows))]
    manifest = json.dumps({'schema': 'cochem-stopped-runtime-source/1', 'target_root': str(root), 'complete_source_freeze': True,
                           'files': rows, 'changes_from_previous_source': {'added': [], 'removed': [], 'changed': list(R5_REPAIRS)}},
                          indent=2).encode('utf-8')
    (root / 'source-manifest.json').write_bytes(manifest)
    after = install_after(root, sha(COMMISSIONED), files['.venv/Scripts/python.exe'])
    after.update(source_manifest_sha256=sha(manifest), reviewed_repairs_sha256=pins, installed_repairs_verified=True)
    after['verification']['r5_repairs_installed'] = True
    after['runtime_bindings'].update(pyvenv_sha256=files['.venv/pyvenv.cfg'], base_python_sha256=sha_file(toolchain / 'python.exe'), base_root=str(toolchain))
    (root / 'install-after.json').write_text(json.dumps(after, indent=4), encoding='utf-8')
    return root


def r5_pin_setup(root: Path) -> str:
    """The retarget-warden-r5 freeze pins (manifest, repair digests, venv bytes) rebound to a make_r5_tree fixture."""
    after = json.loads((root / 'install-after.json').read_text(encoding='utf-8'))
    pins = ';'.join(f"'{relative}'='{digest}'" for relative, digest in after['reviewed_repairs_sha256'].items())
    return (f"$script:r5SourceManifestPin='{after['source_manifest_sha256']}';$script:r5RepairPins=[ordered]@{{{pins}}};"
            f"$script:r5PyvenvPin='{after['runtime_bindings']['pyvenv_sha256']}';$script:r5VenvPythonPin='{after['runtime_bindings']['venv_python_sha256']}';")


def write_staging_receipt(candidate: Path, name='staging-receipt-20261011T101010Z-' + '0123456789abcdef' * 2 + '.json'):
    """The stager's receipt beside a staged candidate (retarget-warden-r5 Assert-StagingReceipt, audit C-F8)."""
    (candidate.parent / name).write_text(json.dumps({'schema': 'cochem-config-only-staging/2', 'status': 'STAGED', 'staged_path': str(candidate),
                                                     'staged_sha256': sha_file(candidate)}), encoding='ascii')


def test_plan_binds_the_r5_install_and_candidate_with_the_imported_retarget_functions(tmp_path):
    base = tmp_path / 'CoChem'
    toolchain = base / 'Toolchain4.2.7-windows-20261006' / 'Python312'
    toolchain.mkdir(parents=True)
    (toolchain / 'python.exe').write_bytes(b'MZ fake toolchain python')
    r5 = make_r5_tree(base, toolchain)
    current = base / 'WardenCommissioning4.2.7-windows-20261007-r3-v1' / 'pipeline.json'
    current.parent.mkdir()
    current.write_bytes(COMMISSIONED)
    held = base / 'held' / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
    enabled = base / 'enabled' / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
    widened = base / 'widened' / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
    widened_doc = json.loads(ENABLED)
    widened_doc['private_root'] = 'D:\\elsewhere'
    unstaged = base / 'unstaged' / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
    for path, data in ((held, COMMISSIONED), (enabled, ENABLED), (widened, json.dumps(widened_doc, indent=2).encode('utf-8')), (unstaged, ENABLED)):
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        if path != unstaged:
            write_staging_receipt(path)
    setup = (r5_pin_setup(r5) +
             f"$script:base='{psq(base)}';$script:r4Root='{psq(R4_ROOT)}';$script:configPin='{sha(COMMISSIONED)}';$script:basePythonRoot='{psq(toolchain)}';"
             f"$script:basePython='{psq(toolchain / 'python.exe')}';$script:probePythonPin='{sha_file(toolchain / 'python.exe')}';"
             f"$script:commissioningConfig='{psq(current)}';$script:r4RestoreConfig='{psq(current)}';"
             r"$script:r5ConfigPattern='^.+\\WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}\\pipeline\.json$';"
             f"$script:targetRoot='{psq(tmp_path / 'never-created')}';"
             "$folder=[pscustomobject]@{};$script:taskCalls=0;$folder|Add-Member ScriptMethod GetTask {param($n) $script:taskCalls++;throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}\n"
             "$hostContext=[pscustomobject]@{admin=$false;name='AETHERDESK\\ansac'}\n")

    def plan(name, candidate, sha_value, install_root='', current_path=current):
        return (f"Invoke-Case '{name}' {{$p=Get-PreviewPlan ([ordered]@{{attempt='{ATTEMPT}';install_root='{psq(install_root)}';current='{psq(current_path)}';"
                f"candidate='{psq(candidate)}';candidate_sha256='{sha_value}';apply=$false}}) $folder $hostContext;"
                "[ordered]@{holds=@($p.holds);verified=$p.document.r5_runtime_verified;mode=$p.document.runner_mode;install_after=$(if($p.document.r5_binding){$p.document.r5_binding.install_after_sha256}else{$null});"
                "python=$(if($p.document.r5_binding){$p.document.r5_binding.python}else{$null});arguments=$(if($p.document.task_action){$p.document.task_action.arguments}else{$null});"
                "daemons=@($p.document.daemon_tasks|ForEach-Object {$_.name+'='+$_.state});schema=$p.document.schema;job_board_opened=$p.document.job_board_opened}}")
    lines = [setup, plan('held', held, sha(COMMISSIONED)), plan('enabled', enabled, sha(ENABLED)), plan('widened', widened, sha_file(widened)),
             plan('commissioning_file', current, sha(COMMISSIONED)), plan('unstaged', unstaged, sha(ENABLED)),
             "Invoke-Case 'enabled_context' {$p=Get-PreviewPlan ([ordered]@{attempt='" + ATTEMPT + "';install_root='';current='" + psq(current) + "';candidate='" +
             psq(enabled) + "';candidate_sha256='" + sha(ENABLED) + "';apply=$false}) $folder $hostContext;"
             "[ordered]@{current=@($p.context.current_providers_sha256.Keys);proposed=@($p.context.proposed_providers_sha256.Keys);"
             "differs=@(@('claude','gemini')|Where-Object {$p.context.current_providers_sha256[$_] -cne $p.context.proposed_providers_sha256[$_]})}}",
             plan('sha_mismatch', enabled, '0' * 64), plan('no_sha', held, ''), plan('root_mismatch', held, sha(COMMISSIONED), install_root=str(base / 'Pipeline4.2.7-windows-20261012-r5')),
             plan('current_other', held, sha(COMMISSIONED), current_path=held), "Invoke-Case 'task_calls' {$script:taskCalls}"]
    cases = run_ps(tmp_path, '\n'.join(lines))
    h = cases['held']['value']
    assert cases['held']['ok'], cases['held']
    assert h['holds'] == [] and h['verified'] is True and h['mode'] == 'held' and h['install_after'] == sha_file(r5 / 'install-after.json')
    assert h['python'] == str(r5 / '.venv' / 'Scripts' / 'python.exe') and h['schema'] == 'cochem-upgrade-preview-r5-plan/1' and h['job_board_opened'] is False
    assert '--mode held' in h['arguments'] and '--nonce <nonce>' in h['arguments'] and f'--install-root "{r5}"' in h['arguments']
    assert h['daemons'] == ['CoChem-4.2.7-Warden=ABSENT', 'CoChem-4.2.7-Supervisor=ABSENT', 'CoChem-4.2.2-Warden=ABSENT', 'CoChem-4.2.3-Supervisor=ABSENT']
    assert cases['enabled']['value']['holds'] == [] and cases['enabled']['value']['mode'] == 'enabled'
    # The Gemini-fallback form (the commissioning copy itself) is held mode as well: the mode follows the bytes.
    assert cases['commissioning_file']['value']['holds'] == [] and cases['commissioning_file']['value']['mode'] == 'held'
    assert cases['enabled_context']['value'] == {'current': ['claude', 'gemini'], 'proposed': ['claude', 'gemini'], 'differs': ['gemini']}, cases['enabled_context']
    expected = {'widened': 'changes more than providers.gemini', 'sha_mismatch': 'differs from the staging receipt sha256', 'no_sha': '-CandidateSha256 from the staging receipt',
                'root_mismatch': 'is not the one installed r5 runtime root', 'current_other': 'must be the commissioned', 'unstaged': 'staging receipt'}
    for name, needle in expected.items():
        assert any(needle in hold for hold in cases[name]['value']['holds']), (name, cases[name])
    assert cases['task_calls']['value'] > 0 and not (tmp_path / 'never-created').exists()


def test_plan_mode_main_makes_no_task_calls_and_creates_nothing(tmp_path):
    body = r'''$script:calls=[ordered]@{new_task=0;register=0;run=0;get_task=0;connect=0}
      function Initialize-PreviewHost {[pscustomobject]@{admin=$false;name='AETHERDESK\ansac'}}
      function Import-PreviewHelpers {}
      function Connect-TaskFolder {$script:calls.connect++
        $scheduler=[pscustomobject]@{};$scheduler|Add-Member ScriptMethod NewTask {param($f)$script:calls.new_task++;throw 'NewTask in plan mode'}
        $folder=[pscustomobject]@{}
        $folder|Add-Member ScriptMethod GetTask {param($n)$script:calls.get_task++;throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}
        $folder|Add-Member ScriptMethod RegisterTaskDefinition {param($a,$b,$c,$d,$e,$f,$g)$script:calls.register++;throw 'Register in plan mode'}
        [pscustomobject]@{scheduler=$scheduler;folder=$folder}}
      function Resolve-R5Install {param($r) [ordered]@{root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5';python='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\.venv\Scripts\python.exe';
        install_after_path='A';install_after_sha256=('1'*64);venv_python_sha256=('2'*64);source_manifest_sha256=('3'*64);revision_sha256=('4'*64);reviewed_repairs=@('src/cochem_pipeline/__main__.py')}}
      function Assert-CurrentConfig {param($p) [ordered]@{path=$p;sha256=$script:configPin;length=1}}
      function Resolve-Candidate {param($p,$s) [ordered]@{path=$p;sha256=$s;length=1;mode='GEMINI_HELD_COMMISSIONED_BYTES'}}
      Invoke-Case 'plan' {Invoke-UpgradePreviewMain -Arguments ([ordered]@{Attempt='__ATTEMPT__';InstallRoot='';Current='C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json';
        Candidate='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json';CandidateSha256='__CONFIG_PIN__';Apply=$false}) -Workspace '__WORKSPACE__'}
      Invoke-Case 'calls' {$script:calls}'''.replace('__ATTEMPT__', ATTEMPT).replace('__WORKSPACE__', psq(ROOT)).replace('__CONFIG_PIN__', m.CONFIG_SHA256)
    before = sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []
    cases = run_ps(tmp_path, body)
    assert cases['plan']['ok'], cases['plan']
    plan = json.loads(cases['plan']['value'])
    assert plan['schema'] == 'cochem-upgrade-preview-r5-plan/1' and plan['mode'] == 'READ_ONLY_PLAN' and plan['holds'] == []
    assert plan['target_root'] == str(COCHEM / ROOT_NAME) and plan['task_name'] == f'CoChem-4.2.7-UpgradePreview-20261011-r5-v1-{ATTEMPT}'
    assert plan['task_execution_time_limit'] == 'PT3M' and plan['task_sddl'] == SDDL and plan['helper_verified'] is True and plan['helper_sha256'] == sha_file(RUNNER)
    assert plan['runner_mode'] == 'held' and plan['tasks_changed'] == 0 and plan['native_models_executed'] is False and plan['job_board_opened'] is False
    assert plan['receipt_path'] == str(COCHEM / ROOT_NAME / 'upgrade-preview-receipt.json')
    assert plan['runner_held_record'] == str(COCHEM / ROOT_NAME / 'upgrade-preview-held.json') and plan['wrapper_held_record'] == str(COCHEM / ROOT_NAME / 'preview-held.json')
    assert plan['task_action']['path'] == r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\.venv\Scripts\python.exe'
    assert plan['task_action']['arguments'].startswith(f'-I -B "{COCHEM / ROOT_NAME / m.HELPER_NAME}" --attempt {ATTEMPT} --nonce <nonce> ')
    calls = cases['calls']['value']
    assert calls['new_task'] == 0 and calls['register'] == 0 and calls['run'] == 0 and calls['connect'] == 1 and calls['get_task'] == 5
    assert (sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []) == before and not (COCHEM / ROOT_NAME).exists()


def test_write_outcome_prints_success_only_for_an_exact_boolean_pass(tmp_path):
    body = r'''$pass=[ordered]@{decision='PASSED';gate=[ordered]@{passed=$true;reasons=@()};message='S10 upgrade preview gate passed'}
      $stop=[ordered]@{decision='GATE_FAILED';gate=[ordered]@{passed=$false;reasons=@('SCHEMA_CHANGES_PRESENT')};message='SERIES-STOP (S10): the upgrade preview gate failed (SCHEMA_CHANGES_PRESENT)'}
      $odd=[ordered]@{decision='PASSED';gate=[ordered]@{passed='true';reasons=@()};message='SERIES-STOP: odd'}
      Invoke-Case 'pass' {(Write-PreviewOutcome $pass|ConvertFrom-Json).message}
      Invoke-Case 'stop' {Write-PreviewOutcome $stop 6>$null}
      Invoke-Case 'odd' {Write-PreviewOutcome $odd 6>$null}'''
    cases = run_ps(tmp_path, body)
    assert cases['pass'] == {'case': 'pass', 'ok': True, 'value': 'S10 upgrade preview gate passed'}
    assert cases['stop']['ok'] is False and cases['stop']['error'].startswith('SERIES-STOP (S10)')
    assert cases['odd']['ok'] is False


# ------------------------------------------------------------------- top level, plan mode only (ps_toplevel_smoke.py)
# The REAL wrapper top level (param block, binding, the hash-pinned helper imports: the 2026-10-11 17:22 failure class and
# the retarget-warden-r5 pin cascade) with the host stubbed; the helper refuses -Apply. RUN_427_R5_SITTING.ps1 S10 runs
# '-Attempt <hex> -CandidateSha256 <staged sha256> -Candidate <staged path>' (plan, then -Apply).

SMOKE_PLAN_SCHEMA = 'cochem-upgrade-preview-r5-plan/1'
SMOKE_CANDIDATE = r'C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v2\pipeline.json'


def test_validated_parameter_variables_are_written_only_with_checked_values():
    body = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + psq(SCRIPT) + "',[ref]$t,[ref]$e);if($e.Count){throw $e[0]};"
            "$v=@{};foreach($p in @($a.ParamBlock.Parameters)){if(@($p.Attributes|Where-Object{$_.TypeName.Name -like 'Validate*'}).Count){$v[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=1}};"
            "$hits=@(foreach($n in $a.FindAll({param($x)$x -is [Management.Automation.Language.AssignmentStatementAst]},$true)){"
            "$targets=@($n.Left);if($n.Left -is [Management.Automation.Language.ArrayLiteralAst]){$targets=@($n.Left.Elements)};"
            "foreach($l in $targets){if($l -is [Management.Automation.Language.ConvertExpressionAst]){$l=$l.Child};if($l -isnot [Management.Automation.Language.VariableExpressionAst]){continue};"
            "$name=($l.VariablePath.UserPath -replace '^(script|global|local|private):','').ToLowerInvariant();"
            "$f=$n.Parent;while($null -ne $f -and $f -isnot [Management.Automation.Language.FunctionDefinitionAst]){$f=$f.Parent};"
            "if($v.ContainsKey($name) -and ($l.VariablePath.IsScript -or $l.VariablePath.IsGlobal -or $null -eq $f)){$l.Extent.Text+'='+$n.Right.Extent.Text}}});"
            "$sv=@($a.FindAll({param($x)$x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -in @('Set-Variable','New-Variable','sv','nv')},$true)).Count;"
            "'RESULT '+(@{validated=@($v.Keys|Sort-Object);hits=@($hits);set_variable=$sv}|ConvertTo-Json -Compress)")
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    value = json.loads(next(line for line in result.stdout.splitlines() if line.startswith('RESULT '))[len('RESULT '):])
    assert value['validated'] == ['attempt'] and value['set_variable'] == 0
    # Set-PreviewConstants receives the -Attempt Assert-PreviewParameters checked (lowercase 32-hex, -cnotmatch).
    assert value['hits'] == ['$script:Attempt=$Attempt']


@pytest.mark.parametrize('invocation', ['file', 'command'])
def test_toplevel_plan_for_the_documented_sitting_call(invocation):
    args = ['-Attempt', ATTEMPT, '-CandidateSha256', 'e' * 64, '-Candidate', SMOKE_CANDIDATE]
    result = smoke.run_toplevel(SCRIPT, args, invocation=invocation)
    assert smoke.plan_mode_outcome(result, plan_schema=SMOKE_PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    assert plan['attempt'] == ATTEMPT and plan['target_root'] == str(COCHEM / ROOT_NAME) and isinstance(plan['holds'], list)
