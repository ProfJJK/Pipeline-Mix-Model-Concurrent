"""Shared initial output contracts; all fixtures are pure and never invoke a CLI."""
from copy import deepcopy
import hashlib
import json

import pytest

from cochem_pipeline.output_contracts import (
    OutputFormatError, invalid_json_output, prepare_output_contract, validate_output_format, normalize_generated_output,
)
from cochem_pipeline.worker import node_prompt
from cochem_pipeline.store import JobStore
from scripts.prepare_job_handoff import prepare


def chapter():
    return dict(kind='CHAPTER_DRAFT', workflow_id='work', job_id='job', chapter_id='storage',
        payload=dict(chapter_id='storage', requirements=['REQ-store'],
            wbs_tasks_defined=[dict(id='storage-save', description='Persist evidence', requirements=['REQ-store'])]))


def test_initial_prompt_and_validator_use_identical_contract_and_known_bindings():
    node = chapter()
    prepared = prepare_output_contract(node)
    prompt = node_prompt(node)
    schema = json.loads(prompt.split('Output JSON schema:\n')[1].split('\n\nPrepared handoff')[0])
    form = json.loads(prompt.split('Prepared handoff form (fill null fields):\n')[1].split('\n\nTrusted baseline')[0])
    assert schema == prepared['output_schema']
    assert form == prepared['handoff']
    assert form['response']['chapter_id'] == 'storage'
    assert form['response']['requirements_traced'] == ['REQ-store']
    assert form['response']['artifact_uri'] == 'db://work/storage'
    assert form['response']['artifact_text'] is None
    assert 'null entries require substantive work' in form['unfilled_values']
    complete = {**form['response'], 'artifact_text': 'Actual storage SRS and WBS'}
    validate_output_format(node, complete)
    JobStore._chapter(node, complete)
    with pytest.raises(OutputFormatError):
        validate_output_format(node, form['response'])


def test_feedback_is_bounded_safe_and_never_exposes_answer_content():
    node = chapter()
    with pytest.raises(OutputFormatError) as caught:
        validate_output_format(node, {'chapter_id': 'storage', 'artifact_text': 42,
                                     'private_reason': 'secret model content'})
    feedback = caught.value.as_feedback()
    assert 'secret model content' not in json.dumps(feedback)
    assert {'path': '$.artifact_text', 'code': 'wrong_type'} in feedback['issues']
    assert feedback['contract_sha256'] == prepare_output_contract(node)['contract_sha256']
    node['output_format_feedback'] = {**feedback, 'correction_attempt': 1}
    assert 'correction 1 of at most 2' in node_prompt(node)
    node['output_format_feedback']['correction_attempt'] = 3
    with pytest.raises(ValueError, match='feedback'):
        node_prompt(node)


def test_contract_change_fences_old_correction_without_modifying_task_payload():
    node = chapter()
    original = deepcopy(node['payload'])
    feedback = invalid_json_output(node).as_feedback()
    assert feedback['issues'] == [{'path': '$', 'code': 'invalid_json'}]
    node['output_format_feedback'] = {**feedback, 'correction_attempt': 1}
    node_prompt(node)
    assert node['payload'] == original
    node['payload']['chapter_id'] = 'another'
    with pytest.raises(ValueError, match='different contract'):
        node_prompt(node)


def test_semantic_identity_failure_is_not_a_format_correction():
    node = chapter()
    output = {**prepare_output_contract(node)['handoff']['response'],
              'artifact_text': 'Actual content', 'chapter_id': 'wrong-owner'}
    with pytest.raises(ValueError, match='commitment') as caught:
        validate_output_format(node, output)
    assert not isinstance(caught.value, OutputFormatError)
    with pytest.raises(ValueError, match='ownership') as caught:
        JobStore._chapter(node, output)
    assert not isinstance(caught.value, OutputFormatError)


def test_wrong_supplied_hash_beats_missing_format_fields():
    node = dict(kind='SYNTHESIS', payload=dict(chapter_hashes={'first': 'a'*64},
        chapter_output_hashes={'first': 'b'*64}, coverage_report_sha256='c'*64,
        wbs_tasks_by_chapter={'first': []}))
    with pytest.raises(ValueError, match='commitment') as caught:
        validate_output_format(node, {'chapter_hashes': {'first': 'f'*64}})
    assert not isinstance(caught.value, OutputFormatError)
    micro = execution_node()
    with pytest.raises(ValueError, match='digest') as caught:
        validate_output_format(micro, {'deliverables': [{'name': 'wrong', 'content': 'data', 'sha256': 'f'*64}]})
    assert not isinstance(caught.value, OutputFormatError)


def test_omitted_controller_wbs_remains_compatible_and_values_are_not_rewritten():
    node = chapter()
    output = {**prepare_output_contract(node)['handoff']['response'], 'artifact_text': 'Actual content'}
    del output['wbs_tasks_defined']
    original = deepcopy(output)
    validate_output_format(node, output)
    assert output == original


def execution_node():
    return dict(kind='TASK_PLAN', workflow_id='workflow', payload=dict(
        planning_intent=dict(stage='MICROTASK_EXECUTION', task_id='task-a', microtask_id='actual-task',
            complexity=2, task_types=['COD-TERM'], predecessor_artifact_hashes={'earlier': 'a'*64},
            task=dict(document=dict(requirements=[dict(id='REQ-real', text='Keep the content')],
                                    release_criteria=['Matches specification']))),
        microtask_node=dict(requirement_ids=['REQ-real'], deliverables=['real-output.md'],
                            release_criteria=['Matches specification'])))


def test_execution_form_uses_exact_microtask_requirements_deliverables_and_hashes():
    node = execution_node()
    form = prepare_output_contract(node)['handoff']
    assert form['response']['deliverables'] == [dict(name='real-output.md', content=None, sha256=None)]
    assert form['response']['requirement_evidence'][0]['requirement_id'] == 'REQ-real'
    assert form['response']['release_criteria_results'] == [dict(criterion='Matches specification', passed=None, evidence=None)]
    assert form['assignment']['predecessor_artifact_hashes'] == {'earlier': 'a'*64}
    assert form['assignment']['complexity'] == 2
    assert form['assignment']['task_types'] == ['COD-TERM']
    assert 'actual-task' in node_prompt(node) and 'real-output.md' in node_prompt(node)
    assert '0'*64 not in json.dumps(form)


def test_execution_schema_checks_types_not_success_or_digest_claims():
    from cochem_pipeline.microtask_board_428 import validate_microtask_execution_output
    node = execution_node()
    output = prepare_output_contract(node)['handoff']['response']
    output['artifact_text'] = 'Artifact produced'
    output['deliverables'][0].update(content='hello', sha256=hashlib.sha256(b'hello').hexdigest())
    output['requirement_evidence'][0].update(deliverable_name='real-output.md', verification_evidence='Exact check')
    output['release_criteria_results'][0].update(passed=False, evidence='Does not match')
    validate_output_format(node, output)
    with pytest.raises(ValueError, match='not satisfied') as caught:
        validate_microtask_execution_output(node['payload']['microtask_node'], output)
    assert not isinstance(caught.value, OutputFormatError)
    output['release_criteria_results'][0]['passed'] = 'true'
    with pytest.raises(OutputFormatError):
        validate_output_format(node, output)


def test_offline_handoff_script_never_overwrites_existing_file_or_emits_private_identity(tmp_path):
    node = chapter()
    node.update(attempt_id='private-attempt', fencing_token='private-fence', controller_token='private-token')
    source, destination = tmp_path/'node.json', tmp_path/'handoff.json'
    source.write_text(json.dumps(node), encoding='utf-8')
    result = prepare(source, destination)
    assert result['providers_executed'] == 0
    assert result['status'] == 'HANDOFF_FORM_PREPARED_NOT_EXECUTED'
    raw = destination.read_text(encoding='utf-8')
    assert all(value not in raw for value in ('private-attempt', 'private-fence', 'private-token'))
    with pytest.raises(FileExistsError):
        prepare(source, destination)


@pytest.mark.parametrize('missing', [True, False])
def test_new_content_hashes_are_derived_with_raw_and_normalized_bindings(missing):
    from cochem_pipeline.store import output_digest
    node = execution_node()
    answer = prepare_output_contract(node)['handoff']['response']
    answer['artifact_text'] = 'Summary'
    answer['deliverables'][0]['content'] = 'Exact unicode α\r\nbytes\n'
    if missing:
        del answer['deliverables'][0]['sha256']
    answer['requirement_evidence'][0].update(deliverable_name='real-output.md', verification_evidence='Exact check')
    answer['release_criteria_results'][0].update(passed=True, evidence='Exact check')
    original = deepcopy(answer)
    validate_output_format(node, answer)  # the advertised input schema accepts omission/null
    normalized, evidence = normalize_generated_output(node, answer)
    assert answer == original
    assert normalized['deliverables'][0]['sha256'] == hashlib.sha256('Exact unicode α\r\nbytes\n'.encode()).hexdigest()
    assert evidence['model_output_sha256'] == output_digest(answer)
    assert evidence['accepted_output_sha256'] == output_digest(normalized)
    assert evidence['model_output_sha256'] != evidence['accepted_output_sha256']
    validate_output_format(node, normalized)
    from cochem_pipeline.microtask_board_428 import validate_microtask_execution_output
    validate_microtask_execution_output(node['payload']['microtask_node'], normalized)
    assert normalize_generated_output(node, normalized) == (normalized, None)


def test_supplied_hash_and_upstream_hashes_are_never_repaired():
    from cochem_pipeline.microtask_board_428 import validate_microtask_execution_output
    node = execution_node()
    answer = prepare_output_contract(node)['handoff']['response']
    answer['artifact_text'] = 'Summary'
    answer['deliverables'][0].update(content='content', sha256='f'*64)
    normalized, evidence = normalize_generated_output(node, answer)
    assert normalized is answer and evidence is None
    with pytest.raises(ValueError, match='does not match'):
        validate_microtask_execution_output(node['payload']['microtask_node'], normalized)
    assert node['payload']['planning_intent']['predecessor_artifact_hashes'] == {'earlier': 'a'*64}
    ordinary = chapter()
    unrelated = {'deliverables': [{'content': 'do not touch', 'sha256': None}], 'chapter_hashes': {'one': None}}
    result, evidence = normalize_generated_output(ordinary, unrelated)
    assert result is unrelated and evidence is None


def test_swarm_form_uses_real_members_and_normalization_preserves_identity():
    node = execution_node()
    node['payload']['planning_intent']['stage'] = 'MICROTASK_SWARM_BATCH'
    node['payload']['swarm_batch'] = dict(batch_id='real-batch', provider_family='codex',
        microtask_ids=['actual-task'], subagents=[dict(microtask_id='actual-task', requirement_ids=['REQ-real'],
                                                     deliverables=['real-output.md'], release_criteria=['Exact criterion'])])
    form = prepare_output_contract(node)['handoff']['response']
    assert set(form['subagent_outputs']) == {'actual-task'}
    assert form['subagent_outputs']['actual-task']['deliverables'][0]['name'] == 'real-output.md'
    form['subagent_outputs']['actual-task']['deliverables'][0]['content'] = 'Actual content'
    normalized, evidence = normalize_generated_output(node, form)
    assert normalized['batch_id'] == 'real-batch' and normalized['provider_family'] == 'codex'
    assert evidence['changes'][0]['sha256'] == hashlib.sha256(b'Actual content').hexdigest()
    assert form['subagent_outputs']['actual-task']['deliverables'][0]['sha256'] is None
