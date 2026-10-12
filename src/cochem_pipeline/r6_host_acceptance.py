"""One-shot SYSTEM acceptance phases for the owner-run R6 deployment series.

Importing this module does nothing. The elevated wrapper verifies protected code
and creates a fresh private output root before requesting one scheduled run.
No phase enables a daemon, changes accounts, installs software, or prompts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time

from .r6_candidate import BASE_SHA256, BINARIES, ROOT, from_commissioned_bytes
from .worker import strict_json

COMMISSIONED = Path(r'C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json')


def read_bound(win, path, expected=None, maximum=16 * 1024**2):
    path = Path(path)
    win.validate_code_path(path)
    for current in (path, *path.parents):
        info = current.lstat()
        if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Acceptance input traverses a redirected path')
    info = path.stat()
    if info.st_nlink != 1 or not 0 <= info.st_size <= maximum:
        raise ValueError('Acceptance input exceeds bounds or has alternate links')
    data = path.read_bytes()
    if len(data) != info.st_size or (expected and hashlib.sha256(data).hexdigest() != expected):
        raise ValueError('Acceptance input differs from the pinned bytes')
    return data


def bind_installation(win, manifest_hash, candidate_hash):
    from .config import load_config
    from .deployment_revision import verify_installed_revision
    root = Path(str(ROOT))
    if Path(sys.prefix) != root / '.venv' or Path(sys.executable) != root / '.venv/Scripts/python.exe':
        raise ValueError('Acceptance must use the exact protected R6 interpreter')
    if (root / 'install-held.json').exists():
        raise ValueError('Preserve the held installation')
    manifest = strict_json(read_bound(win, root/'install-manifest.json', manifest_hash).decode())
    installed = strict_json(read_bound(win, root/'install-after.json').decode())
    if (manifest.get('schema') != 'cochem-r6-install-bundle/1'
            or installed.get('status') != 'STOPPED_RUNTIME_INSTALLED'
            or installed.get('manifest_sha256') != manifest_hash
            or installed.get('source_commit') != manifest.get('source_commit')):
        raise ValueError('Installed R6 receipt does not bind this manifest')
    seen = set()
    rows = manifest.get('files')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError('Invalid installed manifest inventory')
    for row in rows:
        name = row['relative']
        if (not isinstance(name, str) or name.casefold() in seen or '\\' in name
                or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))
                or re.search(r'[\x00-\x1f<>:"|?*]', name)):
            raise ValueError('Invalid installed payload path')
        seen.add(name.casefold())
        data = read_bound(win, root/name, row['sha256'], 268435456)
        if type(row['length']) is not int or len(data) != row['length']:
            raise ValueError('Installed payload length differs')
    raw = read_bound(win, root/'pipeline.json', candidate_hash)
    actual = strict_json(raw.decode('utf-8-sig'))
    proposed, plan = from_commissioned_bytes(read_bound(win, COMMISSIONED, BASE_SHA256))
    if actual != proposed:
        raise ValueError('Installed candidate differs from the exact approved transformation')
    revision = verify_installed_revision(root/'source', root/'.venv/Lib/site-packages', root/'source')
    if revision != installed.get('revision'):
        raise ValueError('Installed package revision changed')
    return load_config(root/'pipeline.json'), actual, plan, revision


def auth_checks(config, ram, root):
    """Only status commands. Missing authentication returns an attended-start list."""
    from .windows import WorkerIdentity
    from .worker import NativeRunner, _read_native_output, subscription_status, subscription_probe_status
    from .inference_policy import claude_inference_arguments
    runner, results = NativeRunner(config), []
    for slot in sorted(config.workers):
        identity, descriptor = WorkerIdentity(**config.workers[slot]), ram.workspace(slot)
        for provider in ('codex', 'claude', 'gemini'):
            spec = config.providers[provider]
            arguments = (['login', 'status'] if provider == 'codex' else
                [*claude_inference_arguments(), 'auth', 'status', '--json'] if provider == 'claude' else
                spec['subscription_probe']['arguments'])
            descriptor.environment()
            # Transient raw status remains in private SYSTEM scratch handles.
            # It is never copied into public receipts or exception messages.
            with tempfile.TemporaryFile('w+b', dir=descriptor.scratch) as inp, \
                    tempfile.TemporaryFile('w+b', dir=descriptor.scratch) as out, \
                    tempfile.TemporaryFile('w+b', dir=descriptor.scratch) as err:
                process = runner._launch_worker(identity, [spec['executable'], *arguments], descriptor.root,
                    inp, out, err, worker_slot=slot, limits=config.execution_limits, ramdisk_workspace=descriptor)
                with runner._managed('r6-auth-'+provider+'-'+slot, process):
                    code = runner._wait(process, lambda: True, 30, None,
                        output_streams=(out, err), output_limit_bytes=65536)
                stdout, stderr = _read_native_output(out, err, 65536)
                texts = (stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace'))
                verified = (subscription_probe_status(*texts, code, spec['subscription_probe']) if provider == 'gemini'
                            else subscription_status(provider, *texts, code))
                from .failures import parse_native_failure
                failure = None if verified else parse_native_failure(provider, *texts, code)
                explicit_logout = (provider == 'claude' and _claude_logged_out(texts[0])) or (
                    failure is not None and failure.category == 'auth')
                results.append(dict(worker=slot, provider=provider, authenticated=verified,
                    status='REUSE_VERIFIED_SESSION' if verified else
                        'ATTENDED_LOGIN_REQUIRED' if explicit_logout else 'STATUS_UNVERIFIED',
                    exit_code=code, cleanup_verified=True))
    return dict(schema='cochem-r6-authentication/1',
        status='ALL_SESSIONS_VERIFIED' if all(r['authenticated'] for r in results) else 'ATTENDED_AUTH_REVIEW_REQUIRED',
        checks=results, native_model_jobs_executed=0, credentials_copied=False, activation_ready=False)


def _claude_logged_out(text):
    try:
        data = strict_json(text)
        return isinstance(data, dict) and data.get('loggedIn') is False
    except (ValueError, TypeError):
        return False


def fresh_knowledge(config):
    from .knowledge import KnowledgeService
    from .knowledge_authority import KnowledgeAuthority
    from .planning_governance import canonical_authority
    state = Path(config.knowledge.state_root)
    if state.exists():
        raise ValueError('Preserve the existing R6 knowledge state; no automatic rebuild')
    service = KnowledgeService(config.knowledge)
    try:
        service.refresh(full=True)
        result = KnowledgeAuthority(service, canonical_authority()).status(force=True)
        if result.get('ready') is not True or result.get('authority_matches_capture') is not True:
            raise ValueError('New private knowledge authority is not ready')
        return dict(schema='cochem-r6-knowledge-acceptance/1', status='NEW_KNOWLEDGE_AUTHORITY_VERIFIED',
            evidence=result, old_index_modified=False, activation_ready=False)
    finally:
        service.close()


def run(phase, output, manifest_hash, candidate_hash):
    from . import windows as win
    from .ramdisk import RamdiskManager
    from .r6_agent_acceptance import accept as agent_accept
    from .r6_native_acceptance import run_probes
    win.require_system()
    output = Path(output)
    if (output.parent != Path(r'C:\Program Files\CoChem')
            or not re.fullmatch(r'R6Acceptance4\.2\.7-windows-20261012-v1-(auth|knowledge|agent|native|preview)-[a-f0-9]{32}', output.name)
            or ('-'+phase+'-') not in output.name):
        raise ValueError('Unexpected protected acceptance output root')
    win.validate_private_directory(output)
    if (output/'result.json').exists() or (output/'held.json').exists():
        raise ValueError('Preserve the completed or held acceptance attempt')
    start = time.time()
    try:
        config, raw, plan, revision = bind_installation(win, manifest_hash, candidate_hash)
        ram = RamdiskManager(config.ramdisk, config.private_root,
            {slot: win.WorkerIdentity(**value) for slot, value in config.workers.items()})
        # Inspect only: the existing R: volume, startup task and ledger survive.
        ram.inspect()
        if phase == 'auth':
            result = auth_checks(config, ram, output)
        elif phase == 'agent':
            result = agent_accept(config)
        elif phase == 'knowledge':
            result = fresh_knowledge(config)
        elif phase == 'native':
            # A new private child stores only these synthetic acceptance jobs.
            native_root = output/'native'
            native_root.mkdir()
            win.validate_private_directory(native_root)
            result = run_probes(config, raw, native_root, ram)
        elif phase == 'preview':
            from .upgrade_preview import upgrade_preview
            result = upgrade_preview(COMMISSIONED, Path(str(ROOT))/'pipeline.json')
            if (result['identities'] or result['database']['schema_changes']
                    or result['database']['migration_executed'] is not False
                    or {r['key'] for r in result['configuration_changes']} - {'routing', 'providers', 'knowledge'}):
                raise ValueError('R6 upgrade preview found an unreviewed migration or configuration change')
        else:
            raise ValueError('Unknown R6 acceptance phase')
        record = dict(schema='cochem-r6-system-phase/1', phase=phase, status='PHASE_COMPLETED',
            manifest_sha256=manifest_hash, candidate_sha256=candidate_hash, revision=revision,
            native_plan_sha256=plan['plan_sha256'], result=result,
            started_at=start, finished_at=time.time(), activation_ready=False)
        with (output/'result.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(record, stream, indent=2)
        return record
    except Exception as exc:
        with (output/'held.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(dict(schema='cochem-r6-system-phase/1', phase=phase, status='HELD_PRESERVE_PARTIAL',
                error_type=type(exc).__name__, category=getattr(exc, 'category', None),
                manifest_sha256=manifest_hash, candidate_sha256=candidate_hash,
                automatic_retry=False, late_prompt=False, activation_ready=False), stream, indent=2)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['auth', 'knowledge', 'agent', 'native', 'preview'], required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest-hash', required=True)
    parser.add_argument('--candidate-hash', required=True)
    args = parser.parse_args()
    if any(not re.fullmatch('[a-f0-9]{64}', value) for value in (args.manifest_hash, args.candidate_hash)):
        parser.error('Exact SHA256 inputs are required')
    try:
        record = run(args.phase, args.output, args.manifest_hash, args.candidate_hash)
        print(json.dumps(dict(status=record['status'], phase=args.phase, activation_ready=False)))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status='HELD_PRESERVE_PARTIAL', error_type=type(exc).__name__, activation_ready=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
