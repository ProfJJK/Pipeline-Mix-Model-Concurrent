"""Inert controller proofs; no providers, Git, containers or child processes."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import threading

import pytest

from cochem_pipeline.coding import bind_test_identities, digest, manifest
from cochem_pipeline.container_policy import DockerPolicy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_artifact_runtime_428 import TaskArtifactRuntime
from cochem_pipeline.task_verification_428 import (requirement_test_names,
    verify_task_test_evidence, verify_artifact_evidence)
from pipeline_tests.test_container_policy import enabled


def example(phase='green'):
    names = requirement_test_names(['R1'])
    name = names['R1']
    files = {'tests/test_task.py': f'def {name}():\n    assert 1 == 1\n'.encode(), 'src/a.py': b'value = 1\n'}
    identities = bind_test_identities(files, ['tests/test_task.py'], [{'name': name}])
    policy = DockerPolicy.from_dict(enabled())
    payload = dict(docker=policy.as_dict(), source_snapshot_sha256=digest(manifest(files)),
                   verification_key='a'*64, expected_test_identities=identities,
                   requirement_test_names=names, source_modes={}, test_phase=phase)
    source = {p: dict(sha256=s, size=len(files[p]), executable=False) for p,s in manifest(files).items()}
    case = dict(name=name, class_name='tests.test_task', status='passed')
    evidence = dict(kind='docker-test-execution', image_id=policy.image, policy_sha256=policy.digest,
                    source=dict(files=source, sha256=digest(source)), source_verified=True, cleanup_verified=True,
                    commands=[dict(exit_code=0, junit_cases=[case], junit=dict(tests=1,failures=0,errors=0))],
                    passed=True, failure_category=None)
    if phase == 'red':
        evidence.update(passed=False, failure_category='tests_failed')
        evidence['commands'][0].update(exit_code=1, junit=dict(tests=1,failures=1,errors=0))
        case.update(status='failed', assertion_failure=dict(phase='call',exception_type='AssertionError',
            path=identities[name]['path'],source_sha256=identities[name]['file_sha256'],line=2))
    return payload, evidence, files


@pytest.mark.parametrize('phase', ['red','green'])
def test_exact_physical_test_evidence_accepts_phase(phase):
    payload,evidence,files = example(phase)
    result = verify_task_test_evidence(payload,evidence,files)
    assert result['status'] == 'VERIFIED'
    assert result['verification_kind'] == 'coding_'+phase
    assert result['verified_requirements'] == ['R1']


@pytest.mark.parametrize('field,value', [('cleanup_verified',False),('source_verified',False),
    ('kind','model_claim'),('image_id','sha256:'+'0'*64),('policy_sha256','0'*64)])
def test_runner_or_custody_mismatch_is_not_accepted(field,value):
    payload,evidence,files = example()
    evidence[field]=value
    with pytest.raises(ValueError): verify_task_test_evidence(payload,evidence,files)


@pytest.mark.parametrize('mutation', ['skip','empty','wrong_class','wrong_name'])
def test_green_requires_exact_executed_requirement_identity(mutation):
    payload,evidence,files = example()
    case=evidence['commands'][0]['junit_cases'][0]
    if mutation=='skip': case['status']='skipped'
    elif mutation=='empty': evidence['commands'][0]['junit_cases']=[]
    elif mutation=='wrong_class': case['class_name']='tests.other'
    else: case['name']='test_unrelated'
    assert verify_task_test_evidence(payload,evidence,files)['status']=='REJECTED'


@pytest.mark.parametrize('mutation', ['missing_assertion','wrong_hash','setup_error','passed'])
def test_red_needs_an_executed_assertion_failure(mutation):
    payload,evidence,files = example('red')
    case=evidence['commands'][0]['junit_cases'][0]
    if mutation=='missing_assertion': case.pop('assertion_failure')
    elif mutation=='wrong_hash': case['assertion_failure']['source_sha256']='0'*64
    elif mutation=='setup_error': evidence['commands'][0]['junit']['errors']=1
    else: case['status']='passed'
    assert verify_task_test_evidence(payload,evidence,files)['status']=='REJECTED'


def test_source_bytes_and_sizes_are_bound_even_if_claimed_passed():
    payload,evidence,files=example()
    evidence['source']['files']['src/a.py']['size']+=1
    with pytest.raises(ValueError): verify_task_test_evidence(payload,evidence,files)


@pytest.mark.parametrize('mutation', ['test_name', 'class_name', 'requirement_set'])
def test_exact_source_definition_and_requirement_set_cannot_be_relabelled(mutation):
    payload, evidence, files = example()
    if mutation == 'requirement_set':
        payload['requirements'] = ['R1', 'unverified']
    elif mutation == 'test_name':
        name = payload['requirement_test_names']['R1']
        identity = payload['expected_test_identities'].pop(name)
        payload['expected_test_identities']['test_unrelated'] = identity
        payload['requirement_test_names']['R1'] = 'test_unrelated'
        evidence['commands'][0]['junit_cases'][0]['name'] = 'test_unrelated'
    else:
        name = payload['requirement_test_names']['R1']
        payload['expected_test_identities'][name]['class_name'] = 'forged.module'
        evidence['commands'][0]['junit_cases'][0]['class_name'] = 'forged.module'
    with pytest.raises(ValueError):
        verify_task_test_evidence(payload, evidence, files)
    payload,evidence,files=example()
    files['src/a.py']=b'value = 0\n'
    with pytest.raises(ValueError): verify_task_test_evidence(payload,evidence,files)


def test_content_integrity_does_not_claim_external_action_or_requirement_verification():
    files={'report.md':b'Content'}
    payload=dict(verification_key='c'*64,source_snapshot_sha256=digest(manifest(files)))
    evidence=dict(kind='artifact-integrity',observed_manifest=manifest(files),cleanup_verified=True)
    result=verify_artifact_evidence(payload,evidence,files)
    assert result['passed'] and result['verified_requirements']==[]
    assert result['verification_kind']=='artifact_integrity'
    evidence['observed_manifest']={}
    with pytest.raises(ValueError): verify_artifact_evidence(payload,evidence,files)


def test_physical_fragment_staging_and_durable_capture(tmp_path):
    store=JobStore(tmp_path/'board.db')
    slot=tmp_path/'slot'; slot.mkdir()
    descriptor=SimpleNamespace(root=slot,identity='fixture',validate=lambda **_:None)
    runtime=SimpleNamespace(store=store,coding=None,ramdisk=SimpleNamespace(workspace=lambda _:descriptor))
    artifacts=TaskArtifactRuntime(runtime)
    artifacts.prepare_task('task1',None)
    artifacts.prepare_task('task1',None)
    output=dict(artifact_text='report',deliverables=[dict(name='report.md',content='Verified bytes',
        sha256=hashlib.sha256(b'Verified bytes').hexdigest())],requirement_evidence=[],release_criteria_results=[])
    runtime.runner=SimpleNamespace(run=lambda *a,**k:(deepcopy(output),{'test_fixture':True}))
    intent=dict(stage='SIMPLE_EXECUTION',task_id='task1',task=dict(document=dict(requirements=[{'id':'R1'}])))
    payload=dict(planning_intent=intent)
    payload['execution_context']=artifacts.execution_context(payload)
    with store._write() as conn:
        store._insert(conn,'root','root',None,'MACRO_PLANNING_REQUEST','IN_PROGRESS',{})
        store._insert(conn,'node','root','root','TASK_PLAN','PENDING',payload)
    # Claim only changes lease state; this inert store has no routing catalog.
    node=store.claim('fixture',worker_slot='slot1',requires_cleanup=True)
    result,_=artifacts.run(node,'slot1','',lambda:True,lambda _:None,threading.Event(),
                           on_native_start=lambda _:None,on_native_end=lambda:None)
    assert result==output
    assert (slot/'task-result'/'report.md').read_bytes()==b'Verified bytes'
    with store._connection() as conn:
        row=conn.execute('SELECT * FROM task428_fragment_attempts').fetchone()
    assert row['output_sha256']==digest(output)
    assert store.coding_files(row['snapshot_sha256'])=={'report.md':b'Verified bytes'}
    # Staged bytes are not accepted until the winning native result and cleanup commit.
    with pytest.raises(ValueError,match='winning'): artifacts.accepted_snapshot(node)
    store.close()


def test_no_project_capture_can_be_rebound(tmp_path):
    store=JobStore(tmp_path/'board.db')
    artifacts=TaskArtifactRuntime(SimpleNamespace(store=store,coding=None))
    artifacts.prepare_task('task1',None)
    with pytest.raises(ValueError,match='immutable'): artifacts.prepare_task('task1','different-project')
    store.close()
