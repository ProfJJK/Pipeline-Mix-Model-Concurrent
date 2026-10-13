"""Hash-bound, in-memory repair for the immutable installed R6 directory guard.

Only FILE_LIST_DIRECTORY is added to directory desired access. Neither ACLs,
share modes, acceptance decisions nor installed files are changed. The same
helper is pinned in agent acceptance, native acceptance and the daemon action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import traceback
import types

ORIGINAL = 'd86c90750dc2112ce8ff1bc9a4937898eb35cadbf4362050b04381e2138e6591'
MANIFEST = 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4'
CANDIDATE = 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
ROOT = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r6-v1')
KNOWLEDGE = Path(r'C:\Program Files\CoChem\R6Acceptance4.2.7-windows-20261012-v1-knowledge-47776d31bd0e4773be318bde56f5be0a\result.json')
KNOWLEDGE_HASH = '5bcc2dc08c3edb5c7918e75f66ef33959b5f5cbaf8d62dd1c2c2c86db73a6abf'


def repaired_module(raw):
    """Accept one known source and one literal change, never a generic patch."""
    before, after = b'0x20000 if directory else', b'0x20001 if directory else'
    if hashlib.sha256(raw).hexdigest() != ORIGINAL or raw.count(before) != 1:
        raise ValueError('Custody amendment original module binding differs')
    repaired = raw.replace(before, after)
    module = types.ModuleType('cochem_pipeline._r6_custody_repair')
    module.__package__ = 'cochem_pipeline'
    exec(compile(repaired, '<r6-reviewed-directory-custody>', 'exec'), module.__dict__)
    return module, hashlib.sha256(repaired).hexdigest()


def install(expected_hash):
    from cochem_pipeline import windows as win, agy_agent_guard as guard
    from cochem_pipeline.r6_host_acceptance import read_bound
    win.require_system()
    if Path(sys.prefix) != ROOT / '.venv' or Path(sys.executable) != ROOT / '.venv/Scripts/python.exe':
        raise ValueError('Custody amendment requires the exact installed R6 interpreter')
    own = read_bound(win, Path(__file__), expected_hash, 65536)
    module_path = ROOT / '.venv/Lib/site-packages/cochem_pipeline/agy_agent_guard.py'
    if Path(guard.__file__) != module_path or hasattr(guard, '_r6_custody_amendment'):
        raise ValueError('Custody amendment module identity differs or is already amended')
    module, repaired_hash = repaired_module(read_bound(win, module_path, ORIGINAL, 65536))
    # NativeRunner catches the installed class by identity, not just category.
    # Preserve that public exception contract in the compiled repair's globals.
    module.AgentGuardError = guard.AgentGuardError
    guard.lock_worker_profile = module.lock_worker_profile
    guard._r6_custody_amendment = expected_hash
    # Acceptance imports this function by name; production launch imports it
    # from the guard at each launch. Both must observe this identical repair.
    from cochem_pipeline import r6_agent_acceptance as acceptance
    acceptance.lock_worker_profile = guard.lock_worker_profile
    return dict(schema='cochem-r6-directory-custody-amendment/1',
        helper_sha256=hashlib.sha256(own).hexdigest(), original_guard_sha256=ORIGINAL,
        repaired_guard_sha256=repaired_hash, directory_desired_access=0x20001,
        directory_share_mode=3, installed_files_modified=False, acl_modified=False)


def failure_projection(error):
    """Fixed failure types/categories; never include exception or provider text."""
    names = {'ValueError', 'RuntimeError', 'OSError', 'PermissionError', 'AgentGuardError',
             'WindowsIsolationError', 'KnowledgeError', 'DatabaseError', 'FileNotFoundError',
             'ProviderFailure', 'AgyIdentityError', 'AgyToolRegistryError'}
    kind = type(error).__name__
    frames = [dict(function=f.name, line=f.lineno) for f in traceback.extract_tb(error.__traceback__)
              if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,79}', f.name)][-6:]
    result = dict(schema='cochem-r6-amendment-failure/1',
        error_type=kind if kind in names else 'OtherError', frames=frames,
        raw_error_published=False)
    category = getattr(error, 'category', None)
    if isinstance(category, str) and category in {
            'compatibility', 'protocol', 'code', 'auth', 'quota', 'busy', 'provider',
            'resource', 'timeout', 'unknown', 'configuration'}:
        result['category'] = category
    if error.__cause__ is not None:
        cause = type(error.__cause__).__name__
        result['cause_type'] = cause if cause in names else 'OtherError'
    return result


def save_failure(error, output):
    """Private fixed metadata; the wrapper publishes only this allowlisted form."""
    from cochem_pipeline import windows as win
    win.require_system()
    root = Path(output)
    if root.parent != ROOT.parent or not re.fullmatch(r'R6Acceptance4\.2\.7-windows-20261012-v1-(agent|knowledge|native)-[a-f0-9]{32}', root.name):
        raise ValueError('Unexpected amendment failure root')
    win.validate_private_directory(root)
    with (root / 'amendment-failure.json').open('x', encoding='utf-8') as stream:
        json.dump(failure_projection(error), stream)


def verify_existing_knowledge(config):
    from cochem_pipeline import windows as win
    from cochem_pipeline.r6_host_acceptance import read_bound
    from cochem_pipeline.knowledge import KnowledgeService, _ancestors, _read_bytes
    from cochem_pipeline.knowledge_authority import KnowledgeAuthority
    from cochem_pipeline.planning_governance import canonical_authority
    prior = json.loads(read_bound(win, KNOWLEDGE, KNOWLEDGE_HASH))
    if (prior.get('phase') != 'knowledge' or prior.get('status') != 'PHASE_COMPLETED'
            or prior.get('manifest_sha256') != MANIFEST or prior.get('candidate_sha256') != CANDIDATE
            or prior['result']['status'] != 'NEW_KNOWLEDGE_AUTHORITY_VERIFIED'):
        raise ValueError('Completed knowledge receipt differs')
    state = Path(config.knowledge.state_root)
    # Never let the service constructor create missing state on a recovery.
    win.validate_private_directory(state)
    def read_state(path, maximum):
        # State lives under private ProgramData, not a privileged code root.
        # Use the installed knowledge reader's private ACL, ordinary-file,
        # size, file-identity and modification checks. No permission changes.
        _ancestors(path.parent)
        return _read_bytes(path, maximum, private=True)
    pointer = read_state(state / 'current.json', 16384)
    current = json.loads(pointer)
    previous = prior['result']['evidence']
    if not re.fullmatch(r'g-[0-9a-f]{32}', str(current.get('generation', ''))) or current['generation'] != previous['generation']:
        raise ValueError('Completed knowledge generation differs')
    index = state / current['generation'] / 'knowledge_index.db'
    before = read_state(index, 128 * 1024**2)
    service = KnowledgeService(config.knowledge)
    try:
        evidence = KnowledgeAuthority(service, canonical_authority()).status(force=True)
        with service._verification_reader() as (_, reader):
            if reader.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Published knowledge integrity differs')
        for key, value in current.items():
            if evidence.get(key) != value or previous.get(key) != value:
                raise ValueError('Completed knowledge publication metadata differs')
        if evidence.get('ready') is not True or evidence.get('authority_matches_capture') is not True:
            raise ValueError('Completed knowledge authority is not ready')
    finally:
        service.close()
    if pointer != read_state(state / 'current.json', 16384) or before != read_state(index, 128 * 1024**2):
        raise ValueError('Knowledge changed during read-only verification')
    return dict(schema='cochem-r6-knowledge-reuse/1', status='EXISTING_KNOWLEDGE_AUTHORITY_VERIFIED',
        prior_receipt_sha256=KNOWLEDGE_HASH, generation=current['generation'],
        index_sha256=hashlib.sha256(before).hexdigest(), integrity_check='ok',
        evidence=evidence, rebuilt=False, existing_state_modified=False, activation_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('agent', 'knowledge'), required=True)
    for name in ('output', 'manifest-hash', 'candidate-hash', 'custody-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if (args.manifest_hash, args.candidate_hash) != (MANIFEST, CANDIDATE):
        raise ValueError('Custody continuation requires the exact R6 installation')
    from cochem_pipeline import r6_host_acceptance as host, r6_agent_acceptance as agent
    original_agent, original_knowledge = agent.accept, host.fresh_knowledge
    def accept(config):
        result = original_agent(config)
        result['agent_custody_amendment'] = evidence
        return result
    try:
        evidence = install(args.custody_sha256)
        agent.accept, host.fresh_knowledge = accept, verify_existing_knowledge
        host.run(args.phase, args.output, args.manifest_hash, args.candidate_hash)
    except Exception as error:
        save_failure(error, args.output)
        raise
    finally:
        agent.accept, host.fresh_knowledge = original_agent, original_knowledge


if __name__ == '__main__':
    main()
