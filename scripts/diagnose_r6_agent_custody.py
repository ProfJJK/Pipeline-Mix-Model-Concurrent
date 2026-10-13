"""Owner-run, handle-only diagnostic of the unchanged installed RG4 check.

Does not run providers, refresh knowledge, edit profiles/ACLs or change daemons.
The wrapper supplies protected code and a fresh private output directory.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import time
import traceback

MANIFEST = 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4'
CANDIDATE = 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
BASE = Path(r'C:\Program Files\CoChem')
PRIOR = {
    'agent': 'R6Acceptance4.2.7-windows-20261012-v1-agent-0269bb0c420b488bbb4874841be21ea0/held.json',
    'auth': 'R6Acceptance4.2.7-windows-20261012-v1-auth-9e0a79eaef0d4c2eb749842913ce38ec/result.json',
    'knowledge': 'R6Acceptance4.2.7-windows-20261012-v1-knowledge-47776d31bd0e4773be318bde56f5be0a/result.json',
}
REASONS = {
    'Unexpected Agy discovery path topology': 'PATH_TOPOLOGY',
    'Pre-existing contention or an invalid discovery path': 'BASELINE_PATH_OR_CONTENTION',
    'Profile control did not demonstrate worker delete access': 'PROFILE_DELETE_CONTROL_DENIED',
    'Production guard did not retain every discovery path': 'RETAINED_HANDLE_COUNT',
    'Worker obtained replacement/write access during custody': 'CUSTODY_ACCESS_NOT_DENIED',
    'Access did not return to its original state after guard cleanup': 'BASELINE_NOT_RESTORED',
    'Profile path exceeds bounds': 'PROFILE_PATH_BOUND',
}


def failure(error):
    """No raw exception, identity, path, source line or native output is exported."""
    name = type(error).__name__
    names = {'ValueError', 'RuntimeError', 'OSError', 'PermissionError', 'TimeoutError',
             'AgentGuardError', 'WindowsIsolationError', 'FileNotFoundError', 'RamdiskError'}
    frames = []
    for frame in traceback.extract_tb(error.__traceback__):
        if Path(frame.filename).name in {
            'diagnose_r6_agent_custody.py', 'r6_agent_acceptance.py', 'agy_agent_guard.py',
            'r6_host_acceptance.py', 'ramdisk.py', 'windows.py'} and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,79}', frame.name):
            frames.append(dict(function=frame.name, line=frame.lineno))
    winerror = getattr(error, 'winerror', None)
    return dict(error_type=name if name in names else 'OtherError',
        reason=REASONS.get(str(error), 'UNCLASSIFIED'),
        winerror=winerror if type(winerror) is int else None, frames=frames[-6:])


class TraceChecks:
    """Wrap the actual acceptance adapter without changing its decisions."""
    def __init__(self, inner, row):
        self.inner, self.row, self.calls = inner, row, 0
        row.update(stage='token', token_acquired=False, token_closed=False,
                   guard_acquired=False, guard_closed=False, observations=[])

    def token(self, identity):
        token = self.inner.token(identity)
        self.row['token_acquired'] = True
        return token

    def close_token(self, token):
        self.inner.close_token(token)
        self.row['token_closed'] = True

    def profile(self, token):
        self.row['stage'] = 'profile_lookup'
        return self.inner.profile(token)

    def sid(self, identity):
        self.row['stage'] = 'identity_lookup'
        return self.inner.sid(identity)

    def check(self, token, requests):
        stage = ('before', 'during', 'after')[self.calls]
        self.calls += 1
        self.row['stage'] = stage
        codes = self.inner.check(token, requests)
        if len(requests) != 11 or len(codes) > 11 or any(type(c) is not int or not 0 <= c <= 0xffffffff for c in codes):
            raise ValueError('Diagnostic adapter output exceeds bounds')
        # Index order comes from the unchanged production discovery_paths.
        self.row['observations'].append(dict(stage=stage, request_count=len(requests), codes=list(codes)))
        return codes

    def guard(self, token, sid, contract):
        self.row['stage'] = 'guard_acquire'
        guard = self.inner.guard(token, sid, contract)
        self.row.update(guard_acquired=True, retained_handles=len(guard.handles))
        row = self.row

        class TracedGuard:
            handles = guard.handles

            def close(self):
                guard.close()
                row['guard_closed'] = True

        return TracedGuard()


class Reservation:
    """Same SID-scoped lifetime reservation as the installed native launcher."""
    def __init__(self, win, identity):
        self.win, self.handle = win, None
        sid = win._sid_text(win._account_sid(identity['name']))
        C.set_last_error(0)
        handle = win._api()['kernel32'].CreateMutexW(None, False, 'Global\\CoChemPipeline422-' + sid)
        code = C.get_last_error()
        win._check(handle, 'Reserve diagnostic worker identity')
        if code == 183:
            win._close(handle)
            raise RuntimeError('Worker identity is already reserved')
        self.handle = handle

    def close(self):
        handle, self.handle = self.handle, None
        if handle:
            self.win._check(self.win._api()['kernel32'].CloseHandle(handle), 'Release diagnostic worker identity')


def observe(config, api, reserve, verify):
    from cochem_pipeline.agy_agent_guard import require_agent_contract
    contract = require_agent_contract(config.providers['gemini'])
    if set(config.workers) != {f'slot{i}' for i in range(1, 7)} or config.max_execution_slots != 4:
        raise ValueError('Unexpected worker topology')
    rows = []
    for slot, identity in sorted(config.workers.items()):
        row = dict(slot=slot, stage='reservation', reservation_acquired=False,
                   reservation_closed=False, check_passed=False)
        rows.append(row)
        lease = None
        try:
            lease = reserve(identity)
            row['reservation_acquired'] = True
            verify(TraceChecks(api, row), identity, contract)
            row.update(check_passed=True, stage='completed')
        except Exception as error:
            row['failure'] = failure(error)
        finally:
            if lease is not None:
                try:
                    lease.close()
                    row['reservation_closed'] = True
                except Exception as error:
                    row['cleanup_failure'] = failure(error)
        row['handle_cleanup_observed'] = (
            row['reservation_closed']
            and (not row.get('token_acquired', False) or row.get('token_closed', False))
            and (not row.get('guard_acquired', False) or row.get('guard_closed', False)))
        if not row['check_passed'] or not row['handle_cleanup_observed']:
            break
    return rows


def prior_evidence(win, read_bound):
    evidence = {}
    for phase, relative in PRIOR.items():
        raw = read_bound(win, BASE / relative, maximum=1048576)
        value = json.loads(raw)
        status = 'HELD_PRESERVE_PARTIAL' if phase == 'agent' else 'PHASE_COMPLETED'
        if (value.get('schema') != 'cochem-r6-system-phase/1' or value.get('phase') != phase
                or value.get('status') != status or value.get('manifest_sha256') != MANIFEST
                or value.get('candidate_sha256') != CANDIDATE):
            raise ValueError('Prior receipt binding differs')
        evidence[phase] = dict(sha256=hashlib.sha256(raw).hexdigest(), status=status)
    return evidence


def main():
    # No provider/model subprocess exists in this helper. Only the owner wrapper
    # runs this file, using -I -B and the exact protected installed interpreter.
    from cochem_pipeline import windows as win
    from cochem_pipeline.r6_host_acceptance import bind_installation, read_bound
    from cochem_pipeline.r6_agent_acceptance import WindowsChecks, verify_worker
    from cochem_pipeline.ramdisk import RamdiskManager
    root = Path(__file__).parent
    if root.parent != BASE or not re.fullmatch(r'R6AgentDiagnostic427-[a-f0-9]{32}', root.name):
        raise ValueError('Unexpected diagnostic root')
    win.require_system()
    win.validate_private_directory(root)
    target = root / 'result.json'
    if target.exists():
        raise ValueError('Preserve existing diagnostic')
    report = dict(schema='cochem-r6-agent-diagnostic/1', status='DIAGNOSTIC_HELD',
        stage='binding', started_at=time.time(), manifest_sha256=MANIFEST, candidate_sha256=CANDIDATE,
        activation_ready=False, acceptance_decisions_unchanged=True, automatic_retry=False,
        native_model_jobs_executed=0, provider_commands_executed=0, existing_state_modified=False)
    try:
        config, _, _, _ = bind_installation(win, MANIFEST, CANDIDATE)
        report['stage'] = 'prior_evidence'
        report['prior_evidence'] = prior_evidence(win, read_bound)
        # Reproduce the phase's preceding read-only RAM check as well: the old
        # receipt cannot distinguish its failure from the handle-check failure.
        report['stage'] = 'ram_inspection'
        ram = RamdiskManager(config.ramdisk, config.private_root,
            {slot: win.WorkerIdentity(**identity) for slot, identity in config.workers.items()})
        ram.inspect()
        report['ram_inspection_passed'] = True
        report['stage'] = 'worker_observation'
        report['workers'] = observe(config, WindowsChecks(), lambda identity: Reservation(win, identity), verify_worker)
        report['status'] = 'DIAGNOSTIC_CAPTURED'
    except Exception as error:
        report['failure'] = failure(error)
    report['finished_at'] = time.time()
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, indent=2)
    # A captured failed acceptance check is a successful diagnostic, never
    # authority to accept, deploy or replay the previous acceptance.
    return 0 if report['status'] == 'DIAGNOSTIC_CAPTURED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
