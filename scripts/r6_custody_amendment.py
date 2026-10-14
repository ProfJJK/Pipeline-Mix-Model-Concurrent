"""Exact-source, in-memory custody and Agy registry repairs for installed R6.

Directory handles add FILE_LIST_DIRECTORY without changing ACLs or sharing.
The optional registry repair binds Agy 1.3.1 and the selected protected agent;
the CLI's global advertisement is not agent permission evidence. Actual tool
steps remain forbidden. Acceptance and startup pin this same helper. Installed
files are never changed.
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

from cochem_pipeline.agy_agent_guard import require_agent_contract

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


def install(expected_hash, *, registry=False):
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
    evidence = dict(schema='cochem-r6-directory-custody-amendment/1',
        helper_sha256=hashlib.sha256(own).hexdigest(), original_guard_sha256=ORIGINAL,
        repaired_guard_sha256=repaired_hash, directory_desired_access=0x20001,
        directory_share_mode=3, installed_files_modified=False, acl_modified=False)
    if registry:
        evidence['tool_registry_amendment'] = install_registry(win, read_bound)
    return evidence


# Separate, exact-source repair. The original installed files remain unchanged.
REGISTRY_PROTOCOL = '2738b76b140e5bc25860c78a457dd91464b57681b607e44096d4d3bc30317ce2'
REGISTRY_WORKER = 'cb528d87f75c9b05f653aea0d3c23370e5d0f0632869afaca4d37be4e68bf147'
FAILURES_ORIGINAL = '625f9c6e045f6a108be04a6a13767593db08ac960bb3839fade0a37e36c6edf5'
CLAUDE_HTTP_STATUS = r'^(?:(?:failed to authenticate\.\s*)?api error:\s*|(?:api error:\s*)?request failed with status code )([0-9]{3})\b'
BINARY_SHA256 = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
AGENT_SHA256 = '5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810'


def failure_module(raw, original):
    """Preserve the immutable runtime while repairing one known HTTP prefix."""
    before = "_CLAUDE_RESULT_API_STATUS = r'^(?:failed to authenticate\\.\\s*)?api error:\\s*([0-9]{3})\\b'"
    if hashlib.sha256(raw).hexdigest() != FAILURES_ORIGINAL:
        raise ValueError('Claude failure amendment original source binding differs')
    text = raw.decode('utf-8')
    if text.count(before) != 1:
        raise ValueError('Claude failure amendment anchor differs')
    text = text.replace(before, "_CLAUDE_RESULT_API_STATUS = " + repr(CLAUDE_HTTP_STATUS))
    clone = types.ModuleType('cochem_pipeline._r6_claude_failure')
    clone.__package__ = 'cochem_pipeline'
    exec(compile(text, '<r6-reviewed-claude-http-failure>', 'exec'), clone.__dict__)
    clone.ProviderFailure = original.ProviderFailure
    return clone


def codex_inherited_workspace_command(argv, workspace, descriptor, identity):
    """Use the isolated process cwd; avoid Codex's strict --cd canonicalization.

    ImDisk's DOS final-path query returns ERROR_INVALID_FUNCTION. The Windows
    launcher already validates the RAM descriptor, owner, volume and no-reparse
    ancestry before assigning this exact cwd to the suspended worker process.
    No host path resolution or alternate workspace is introduced here.
    """
    directory = Path(workspace)
    if (descriptor is None or descriptor.identity != identity or not directory.is_absolute()
            or '..' in directory.parts
            or not directory.is_relative_to(Path(descriptor.root))):
        raise ValueError('Codex inherited cwd requires its assigned RAM workspace')
    if (argv.count('--cd') != 1 or '-C' in argv
            or any(arg.startswith(('--cd=', '-C=')) for arg in argv)):
        raise ValueError('Codex explicit cwd argument differs')
    index = argv.index('--cd')
    if index + 1 >= len(argv) or argv[index + 1] != str(workspace):
        raise ValueError('Codex explicit cwd differs from the launch directory')
    return [*argv[:index], *argv[index + 2:]]


def validate_registry(init, spec):
    """Return metadata, never treat advertised tool names as granted powers."""
    contract = require_agent_contract(spec)
    native = spec['inference_only']
    if (native['executable_sha256'] != BINARY_SHA256 or native['version'] != '1.3.1'
            or contract['sha256'] != AGENT_SHA256 or contract['bytes'] != 478):
        raise ValueError('CLI registry interpretation requires the exact reviewed Agy build and agent')
    if init.get('agent') != contract['name']:
        raise ValueError('Agy did not select the protected inference-only agent')
    names = init.get('tools')
    if (not isinstance(names, list) or len(names) > 256
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,128}', name)
                   for name in names)
            or len(set(names)) != len(names)):
        raise ValueError('Agy CLI registry is malformed or unbounded')
    return dict(schema='cochem-agy-cli-registry/1', scope='cli_builtin_runners',
                advertised_count=len(names), advertised_tools_are_agent_permissions=False,
                agent=contract['name'], agent_sha256=contract['sha256'],
                executable_sha256=BINARY_SHA256)


def registry_modules(protocol_raw, worker_raw, spec, protocol, worker, *, failure_parser=None):
    """Compile only known source bytes; publish no changed callbacks on error."""
    import ast
    if (hashlib.sha256(protocol_raw).hexdigest() != REGISTRY_PROTOCOL or
            hashlib.sha256(worker_raw).hexdigest() != REGISTRY_WORKER):
        raise ValueError('Registry amendment original source binding differs')
    changes = (
        ("    if init.get('tools') != []:\n        raise AgyToolRegistryError('Agy stream did not attest an empty native tool registry')",
         "    try:\n        registry = _registry_validate(init, _registry_spec)\n    except (ValueError, TypeError, KeyError) as exc:\n        raise AgyToolRegistryError('Agy reviewed agent or CLI registry binding differs') from exc"),
        ("            'terminal_success': True,", "            'terminal_success': True, 'tool_registry': registry,"))
    text = protocol_raw.decode('utf-8')
    for before, after in changes:
        if text.count(before) != 1: raise ValueError('Registry protocol repair anchor differs')
        text = text.replace(before, after)
    clone = types.ModuleType('cochem_pipeline._r6_registry_protocol')
    clone.__package__ = 'cochem_pipeline'
    exec(compile(text, '<r6-reviewed-registry-protocol>', 'exec'), clone.__dict__)
    clone.AgyIdentityError, clone.AgyToolRegistryError = protocol.AgyIdentityError, protocol.AgyToolRegistryError
    clone._registry_validate, clone._registry_spec = validate_registry, spec
    changes = (
        ("                                    inference_only=inference_only,mcp_names=mcp_names)",
         "                                    inference_only=inference_only,mcp_names=mcp_names)\n            if provider == 'codex':\n                argv = codex_inherited_workspace_command(argv, workspace, ramdisk_workspace, identity.name)\n                inference_evidence['workspace_selection'] = 'validated_process_cwd'"),
        ("                'identity_policy': identity_policy,", "                'identity_policy': identity_policy, 'tool_registry': parsed['tool_registry'],"),
        ("                receipt['inference_policy'] = inference_evidence", "                if provider == 'gemini':\n                    inference_evidence['tool_registry'] = parsed.get('tool_registry')\n                receipt['inference_policy'] = inference_evidence"))
    worker_text = worker_raw.decode('utf-8')
    for before, after in changes:
        if worker_text.count(before) != 1: raise ValueError('Registry worker repair anchor differs')
        worker_text = worker_text.replace(before, after)
    tree = ast.parse(worker_text)
    parse = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'parse_gemini')
    runner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'NativeRunner')
    run = next(n for n in runner.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
    run.name = '_registry_native_run'
    selected = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), parse, run], type_ignores=[])
    namespace = dict(worker.__dict__)
    if failure_parser is not None:
        namespace['parse_native_failure'] = failure_parser
    namespace['codex_inherited_workspace_command'] = codex_inherited_workspace_command
    exec(compile(ast.fix_missing_locations(selected), '<r6-reviewed-registry-worker>', 'exec'), namespace)
    return clone.parse_stream, namespace['parse_gemini'], namespace['_registry_native_run']


def install_registry(win, read_bound):
    from cochem_pipeline import agy_protocol as protocol, worker, failures
    base = ROOT / '.venv/Lib/site-packages/cochem_pipeline'
    if (Path(protocol.__file__) != base / 'agy_protocol.py' or Path(worker.__file__) != base / 'worker.py'
            or Path(failures.__file__) != base / 'failures.py'
            or hasattr(protocol, '_r6_registry_amendment')):
        raise ValueError('Registry amendment module identity differs or is already installed')
    candidate = json.loads(read_bound(win, ROOT / 'pipeline.json', CANDIDATE, 4194304))
    spec = candidate['providers']['gemini']
    # Verify the exact pair before replacing any callback. This is not a model probe.
    validate_registry({'agent': 'cochem-inference-only', 'tools': []}, spec)
    failure_repair = failure_module(read_bound(win, base / 'failures.py', FAILURES_ORIGINAL, 65536), failures)
    functions = registry_modules(read_bound(win, base / 'agy_protocol.py', REGISTRY_PROTOCOL, 65536),
        read_bound(win, base / 'worker.py', REGISTRY_WORKER, 131072), spec, protocol, worker,
        failure_parser=failure_repair.parse_native_failure)
    worker._CLAUDE_RESULT_API_STATUS = re.compile(CLAUDE_HTTP_STATUS)
    worker.parse_native_failure = failure_repair.parse_native_failure
    protocol.parse_stream, worker.parse_gemini, worker.NativeRunner.run = functions
    protocol._r6_registry_amendment = BINARY_SHA256
    return dict(schema='cochem-r6-agy-registry-amendment/1', protocol_sha256=REGISTRY_PROTOCOL,
                worker_sha256=REGISTRY_WORKER, executable_sha256=BINARY_SHA256,
                agent_sha256=AGENT_SHA256, advertised_registry_scope='cli_builtin_runners',
                agent_identity_required=True, actual_tool_steps_rejected=True,
                codex_workspace_selection='validated_process_cwd',
                claude_failed_result_http_status=True, failures_sha256=FAILURES_ORIGINAL,
                installed_files_modified=False)


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
