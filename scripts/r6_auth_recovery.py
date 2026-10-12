"""Pinned, standalone status-only helper for the already installed R6 runtime.

The owner wrapper copies this file to a fresh protected phase folder. It uses
the installed binding, identity, resource, RAM and cleanup implementations;
it neither patches the installed package nor runs inference. Unknown Agy status
output is retained only in the protected phase root. Public results contain
fixed classifications and hashes, never arbitrary provider output.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import tempfile

from cochem_pipeline.worker import strict_json


SIGN_OUT = frozenset({
    'Please sign in to view available models. Launch the CLI without arguments to sign in.',
    'Error: Please sign in to view available models. Launch the CLI without arguments to sign in.',
    'You are not logged into Antigravity.',
})
FETCHING = 'Fetching available models...'


def classify_agy_status(stdout, stderr, code):
    """Only for the pinned `--output-format json models` command, never answers."""
    from cochem_pipeline.failures import parse_native_failure, native_failure_summary
    failure = parse_native_failure('gemini', stdout, stderr, code)
    try:
        envelope = strict_json(stdout)
    except (ValueError, TypeError, RecursionError):
        envelope = None
    command = envelope.get('command') if isinstance(envelope, dict) else None
    data = command.get('data') if isinstance(command, dict) else None
    models = data.get('models') if isinstance(data, dict) else None
    success = bool(code == 0 and failure is None and isinstance(envelope, dict)
        and envelope.get('status') == 'SUCCESS' and isinstance(command, dict)
        and command.get('name') == 'models' and isinstance(models, list) and models
        and all(isinstance(row, dict) and isinstance(row.get('id'), str)
                and isinstance(row.get('label'), str) for row in models)
        and any(row['id'].startswith('gemini-') for row in models)
        and all(line.strip() == FETCHING for line in stderr.splitlines() if line.strip()))
    lines = [line.strip() for text in (stdout, stderr) for line in text.splitlines() if line.strip()]
    # Preserve the exact historically captured plain-text sign-out protocol.
    # Any extra unclassified error keeps the status unresolved, not a login.
    explicit = code != 0 and bool(lines) and any(line in SIGN_OUT for line in lines) \
        and all(line in SIGN_OUT or line == FETCHING for line in lines)
    typed_auth = failure is not None and failure.category == 'auth'
    logout = not success and (explicit or typed_auth)
    return dict(authenticated=success,
        status='REUSE_VERIFIED_SESSION' if success else 'ATTENDED_LOGIN_REQUIRED' if logout else 'STATUS_UNVERIFIED',
        reason='AGY_MODELS_CATALOG_VERIFIED' if success else
            'AGY_MODELS_EXPLICIT_SIGN_OUT' if explicit else 'TYPED_AUTH_FAILURE' if typed_auth else 'AGY_STATUS_UNRESOLVED',
        failure_category=failure.category if failure is not None else None,
        diagnostic_hint=None if success else 'Subscription authentication failed' if logout else native_failure_summary(stderr),
        stdout_bytes=len(stdout.encode('utf-8')), stderr_bytes=len(stderr.encode('utf-8')),
        stdout_sha256=hashlib.sha256(stdout.encode('utf-8')).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr.encode('utf-8')).hexdigest())


def preserve_unknown_status(root, slot, stdout, stderr):
    """Create-only private evidence; never publish text or overwrite a probe."""
    from cochem_pipeline.windows import validate_private_directory
    validate_private_directory(root)
    if slot not in {f'slot{i}' for i in range(1, 7)} or len(stdout) + len(stderr) > 65536:
        raise ValueError('Invalid bounded status evidence')
    for name, raw in (('stdout', stdout), ('stderr', stderr)):
        with (Path(root)/f'agy-{slot}-unknown.{name}').open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def auth_checks(config, ram, root):
    from cochem_pipeline.windows import WorkerIdentity
    from cochem_pipeline.worker import NativeRunner, _read_native_output, subscription_status
    from cochem_pipeline.inference_policy import claude_inference_arguments
    from cochem_pipeline.r6_host_acceptance import _claude_logged_out
    from cochem_pipeline.failures import parse_native_failure
    runner, results = NativeRunner(config), []
    for slot in sorted(config.workers):
        identity, descriptor = WorkerIdentity(**config.workers[slot]), ram.workspace(slot)
        for provider in ('codex', 'claude', 'gemini'):
            spec = config.providers[provider]
            arguments = (['login', 'status'] if provider == 'codex' else
                [*claude_inference_arguments(), 'auth', 'status', '--json'] if provider == 'claude' else
                ['--output-format', 'json', 'models'])
            if provider == 'gemini' and spec['subscription_probe']['arguments'] != arguments:
                raise ValueError('Recovery requires the exact reviewed Agy status command')
            descriptor.environment()
            with tempfile.TemporaryFile('w+b', dir=descriptor.scratch) as inp, \
                    tempfile.TemporaryFile('w+b', dir=descriptor.scratch) as out, \
                    tempfile.TemporaryFile('w+b', dir=descriptor.scratch) as err:
                process = runner._launch_worker(identity, [spec['executable'], *arguments], descriptor.root,
                    inp, out, err, worker_slot=slot, limits=config.execution_limits, ramdisk_workspace=descriptor)
                with runner._managed('r6-auth-recovery-'+provider+'-'+slot, process):
                    code = runner._wait(process, lambda: True, 30, None,
                        output_streams=(out, err), output_limit_bytes=65536)
                stdout, stderr = _read_native_output(out, err, 65536)
                texts = (stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace'))
                if provider == 'gemini':
                    row = classify_agy_status(*texts, code)
                    if row['status'] == 'STATUS_UNVERIFIED':
                        preserve_unknown_status(root, slot, stdout, stderr)
                else:
                    verified = subscription_status(provider, *texts, code)
                    failure = None if verified else parse_native_failure(provider, *texts, code)
                    logout = (provider == 'claude' and _claude_logged_out(texts[0])) or (
                        failure is not None and failure.category == 'auth')
                    row = dict(authenticated=verified, status='REUSE_VERIFIED_SESSION' if verified else
                        'ATTENDED_LOGIN_REQUIRED' if logout else 'STATUS_UNVERIFIED',
                        failure_category=failure.category if failure is not None else None)
                results.append(dict(row, worker=slot, provider=provider, exit_code=code, cleanup_verified=True))
    return dict(schema='cochem-r6-authentication/1',
        status='ALL_SESSIONS_VERIFIED' if all(r['authenticated'] for r in results) else 'ATTENDED_AUTH_REVIEW_REQUIRED',
        checks=results, status_helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        native_model_jobs_executed=0, credentials_copied=False, activation_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('output', 'manifest-hash', 'candidate-hash'):
        parser.add_argument('--'+key, required=True)
    args = parser.parse_args()
    from cochem_pipeline import r6_host_acceptance as installed
    # Only this one-shot process replaces the callback. run() still verifies
    # SYSTEM, exact sys.prefix, installed files, configuration and revision.
    installed.auth_checks = auth_checks
    installed.run('auth', args.output, args.manifest_hash, args.candidate_hash)


if __name__ == '__main__':
    main()
