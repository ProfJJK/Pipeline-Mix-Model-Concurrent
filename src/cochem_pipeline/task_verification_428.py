"""Physical task evidence. No model text or caller-supplied pass flag is proof."""
from __future__ import annotations

import hashlib

from .coding import digest, manifest
from .container_policy import DockerPolicy
from .pytest_assertions import executed_assertion_failure


def requirement_test_names(requirements):
    return {key: 'test_requirement_' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
            for key in sorted(set(requirements))}


def verify_task_test_evidence(payload, evidence, files):
    """Validate the captured offline runner, exact bytes and actual JUnit cases.

    RED must contain an observed assertion failure, not an import/setup error.
    GREEN must execute every sealed requirement test successfully. This proves
    execution and binding; independent review still owns semantic relevance.
    """
    policy = DockerPolicy.from_dict(payload['docker'])
    if digest(manifest(files)) != payload['source_snapshot_sha256']:
        raise ValueError('Task test snapshot changed')
    source = evidence.get('source') or {}
    index = source.get('files') or {}
    modes = payload.get('source_modes') or {}
    expected = {name: dict(sha256=sha, size=len(files[name]),
                           executable=modes.get(name) == '100755')
                for name, sha in manifest(files).items()}
    if (evidence.get('kind') != 'docker-test-execution'
            or evidence.get('image_id') != policy.image
            or evidence.get('policy_sha256') != policy.digest
            or evidence.get('source_verified') is not True
            or evidence.get('cleanup_verified') is not True
            or index != expected or source.get('sha256') != digest(expected)):
        raise ValueError('Task tests require exact runner, source and cleanup evidence')
    identities = payload['expected_test_identities']
    names = payload['requirement_test_names']
    if not names or set(identities) != set(names.values()):
        raise ValueError('Task tests need a sealed identity for every requirement')
    if any(manifest(files).get(item['path']) != item['file_sha256'] for item in identities.values()):
        raise ValueError('Task test identity is not bound to the tested bytes')
    commands = evidence.get('commands') or []
    cases = [case for command in commands for case in command.get('junit_cases', [])]
    matched = {name: [case for case in cases if case.get('name', '').split('[', 1)[0] == name
                     and case.get('class_name') == identity['class_name']]
               for name, identity in identities.items()}
    if payload['test_phase'] == 'red':
        passed = bool(evidence.get('failure_category') == 'tests_failed'
            and all(matched.values())
            and all(case.get('status') in ('passed', 'failed') for group in matched.values() for case in group)
            and all(command.get('junit', {}).get('errors', 0) == 0 for command in commands)
            and any(command.get('exit_code') == 1 and command.get('junit', {}).get('failures', 0) > 0
                    for command in commands)
            and any(executed_assertion_failure(case, identities[name])
                    for name, group in matched.items() for case in group))
    elif payload['test_phase'] == 'green':
        passed = bool(evidence.get('passed') is True and evidence.get('failure_category') is None
            and len(commands) == len(policy.commands) and all(command.get('exit_code') == 0 for command in commands)
            and all(matched.values()) and all(case.get('status') == 'passed'
                                              for group in matched.values() for case in group))
    else:
        raise ValueError('Unknown task test phase')
    return dict(status='VERIFIED' if passed else 'REJECTED', passed=passed,
                verification_key=payload['verification_key'],
                source_snapshot_sha256=payload['source_snapshot_sha256'],
                verification_kind='coding_' + payload['test_phase'],
                verified_requirements=sorted(names) if passed else [],
                cleanup_verified=True, evidence_sha256=digest(evidence))


def verify_artifact_evidence(payload, evidence, files):
    expected = manifest(files)
    if (digest(expected) != payload['source_snapshot_sha256'] or not files
            or evidence.get('kind') != 'artifact-integrity'
            or evidence.get('observed_manifest') != expected
            or evidence.get('cleanup_verified') is not True):
        raise ValueError('Artifact verification requires the physically observed exact bytes')
    # This is explicitly content-integrity evidence, never an external action,
    # executed code test, or a guarantee of the generated content's correctness.
    return dict(status='VERIFIED', passed=True, verification_key=payload['verification_key'],
                source_snapshot_sha256=payload['source_snapshot_sha256'],
                verification_kind='artifact_integrity', verified_requirements=[],
                cleanup_verified=True, evidence_sha256=digest(evidence))
