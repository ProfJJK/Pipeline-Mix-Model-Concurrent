"""One source of initial output shapes, deterministic forms and format checks.

Format checks deliberately do not replace semantic, provenance, native identity,
receipt or artifact validators. Unfilled form values are null, never evidence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

CODING_NATIVE_KINDS = frozenset({'CODE_PLAN', 'CODE_PLAN_REVIEW', 'CODE_TEST_AUTHOR',
                               'CODE_EDIT', 'CODE_REVIEW', 'CODE_RESEARCH'})

def output_contract_details(node: dict) -> tuple[dict, str, dict]:
    kind, payload = node['kind'], node['payload']
    if kind in ('CODE_EDIT','CODE_RESEARCH'):
        from .diagnostics import bounded_coding_diagnostics
        payload = bounded_coding_diagnostics(payload)
    if kind == 'CODE_PLAN':
        contract = {'goal': payload['objective'], 'srs': {'skeleton': 'Modular SRS outline',
            'chapters': [{'id':'ch01','title':'Implementation requirements','text':'At most 400 lines',
                          'requirement_ids':['R1']}]},
            'acceptance_criteria': [{'id':'AC1','statement':'Observable success','requirement_ids':['R1'],'test_ids':['T1']}],
            'test_cases':[{'id':'T1','name':'test_behavior','asserts':'Concrete assertion','criteria_ids':['AC1']}],
            'leaves':[{'id':'L1','objective':'One bounded code chunk','requirement_ids':['R1'],
                      'criteria_ids':['AC1'],'file_targets':['src/example.py'],'estimated_context_lines':20,'estimated_added_deleted_lines':7,'dependencies':[]}]}
        instruction = ('Plan the actual project coding task before implementation. Inspect the supplied source_context file texts. '
            'Map supplied requirements in order to R1..Rn. Produce modular SRS chapters, explicit acceptance criteria '
            'and tests, and an acyclic FractureManifest of N=1 leaves, each with 20–100 real context lines. '
            'Predict estimated_added_deleted_lines separately from context lines for every leaf, counting source and tests. '
            'The full source-plus-test Git diff for a leaf is at most 100 added-plus-deleted lines. '
            'Use only registered source paths. The controller checks all traces and independently reviews this plan.')
        instruction += (' Follow the controller-supplied COCHEM-4.2.7 execution contract. '
                        'The controller generates and hashes ExecutionContract.json; do not invent additional stage counts or agentic Method Matrix clauses.')
        if payload.get('previous_plan'):
            instruction += (' Revise the supplied previous_plan using every artifact-bound planning_feedback finding. '
                            'Preserve correct material. Every cited artifact group must contain an actual substantive change; '
                            'unchanged resubmissions are held by the controller.')
    elif kind == 'CODE_PLAN_REVIEW':
        contract = {'plan_sha256': payload['plan_sha256'], 'verdict':'PASS',
                    'requirements_checked':list(payload['plan']['requirements']),
                    'artifact_hashes':payload['plan']['artifact_hashes'], 'findings':[]}
        instruction = ('Independently review the exact proposed coding plan against the existing project and request. '
            'Check acceptance criteria, proposed test assertions, modular boundaries and dependency graph. '
            'Do not change any file. A producing model cannot approve its own plan. Return the exact bound plan/artifact digests; '
            'findings must contain severity and issue. Only LOW/INFO findings are compatible with PASS. '
            'Return FAIL or REVISE for an unacceptable plan, with each finding naming its affected artifacts as exact paths; '
            'the controller schedules bounded revisions and never dispatches implementation for non-PASS.')
    elif kind == 'PREFLIGHT_REQUEST':
        contract = {'ready': True}
        instruction = ('Confirm this one native subscription CLI inference by returning exactly ready true. '
                       'Do not use tools, start other agents, read or change files, or claim other providers were tested.')
    elif kind == 'MANIFEST_GENERATOR':
        contract = {
            'chapters': [{'chapter_id': 'unique-id', 'title': 'Chapter title',
                          'requirements': ['one or more provided requirement IDs'],
                          'wbs_tasks_defined': [{'id': 'globally-unique-task-id', 'description': 'Implementable owned task',
                                                 'requirements': ['provided requirement ID owned by this chapter']}]}]
        }
        instruction = ('Return exactly the requested chapter_count chapters. Cover every supplied requirement. '
                       'Each chapter must own a nonempty subset; do not invent requirement IDs. '
                       'Declare 1–256 structured WBS tasks per chapter with globally unique IDs, nonempty descriptions '
                       'and owned requirements that cover all requirements assigned to the chapter.')
    elif kind == 'CHAPTER_DRAFT':
        if not isinstance(payload.get('wbs_tasks_defined'), list) or not payload['wbs_tasks_defined']:
            from .document_governance import DocumentCommitmentHold
            raise DocumentCommitmentHold()
        contract = {
            'chapter_id': payload['chapter_id'], 'requirements_traced': payload['requirements'],
            'wbs_tasks_defined': payload['wbs_tasks_defined'],
            'artifact_uri': f"db://{node['workflow_id']}/{payload['chapter_id']}",
            'artifact_text': 'Full chapter Markdown, including its SRS and WBS',
        }
        instruction = ('Write only your assigned chapter. You have no access to siblings or the job database. '
                       'The Warden stores the artifact in SQLite; do not create a URI file or write a database. '
                       'Trace every assigned requirement to the chapter and WBS. '
                       'The controller copies every supplied WBS declaration verbatim into the accepted wbs_tasks_defined; '
                       'repeat them unchanged or omit them, and never reuse a declared ID for a different task. '
                       'You may append bounded additional tasks owned by this chapter; give each a new ID starting with '
                       '<chapter_id>- so it cannot collide with sibling chapters.')
    elif kind == 'SYNTHESIS':
        if any(key not in payload for key in ('chapter_output_hashes', 'coverage_report_sha256', 'wbs_tasks_by_chapter')):
            from .document_governance import DocumentCommitmentHold
            raise DocumentCommitmentHold()
        contract = {'artifact_text': 'Complete synthesized master SRS/WBS Markdown',
                    'chapter_hashes': payload['chapter_hashes'],
                    'chapter_output_hashes': payload['chapter_output_hashes'],
                    'coverage_report_sha256': payload['coverage_report_sha256'],
                    'wbs_tasks_by_chapter': payload['wbs_tasks_by_chapter']}
        instruction = ('Synthesize all supplied, hash-verified chapters into one master document. '
                       'Preserve the supplied chapter_hashes map exactly; the Warden independently verifies it. '
                       'Use the controller-computed coverage_report to preserve every requested requirement and chapter ownership; '
                       'reconcile reported overlaps without silently dropping any assigned requirement. '
                       'Read each complete accepted_output, including its structured WBS and additional commitments. '
                       'Preserve chapter_output_hashes, coverage_report_sha256 and wbs_tasks_by_chapter exactly.')
    elif kind == 'CODE_TEST_AUTHOR':
        contract = {'requirements_traced': payload['requirements'], 'reuse_tests': [],
                    'artifact_blocks':'<<<FILE: tests/test_example.py>>>\ndef test_example():\n    assert False\n<<<END FILE>>>',
                    'summary': 'Tests authored before implementation'}
        instruction = ('Inspect the provided source_context. Propose targeted regression tests only under test_paths, before source implementation. '
                       'Existing tests and all configuration are protected; never modify or delete them. Author new tests that physically fail '
                       'before implementation. Mock libraries, monkeypatch, encoded mock imports and unfinished stubs are forbidden. Source code must remain unchanged. '
                       'The entire leaf, including implementation and tests, has a 100 added-plus-deleted-line ceiling and 20–100 real context lines. Do not directly modify files. Return complete proposed files '
                       'in artifact_blocks using exact FILE/END FILE markers; the controller alone applies and verifies those bytes.')
    elif kind == 'CODE_EDIT':
        contract = {'requirements_traced': payload['requirements'], 'done': True,
                    'artifact_blocks':'<<<FILE: src/example.py>>>\nComplete replacement file contents\n<<<END FILE>>>',
                    'remaining_work':False, 'summary': 'Actual bounded source change'}
        instruction = ('Implement the requested code in the current project working copy under allowed_paths only. '
                       'Tests were sealed before your implementation and must not change. Do not edit configuration, Git metadata or caches. '
                       'The entire leaf, including its authored tests, may contain at most 100 added-plus-deleted lines. '
                       'Its physical context windows must total 20–100 lines; use adjacent existing source context, never pad edits. '
                       'Mock libraries, monkeypatch, encoded mock imports and unfinished stubs are forbidden. '
                       'Aggregate edits to an existing file may not exceed 500 lines or 80 percent. '
                       'Set done true only when the requested objective is implemented; false requests another tested/reviewed chunk. '
                       'Use the complete target file text supplied in source_context. Return complete proposed files in artifact_blocks '
                       'using exact FILE/END FILE markers. The controller applies bounded changes, runs Docker tests and gets independent review.')
    elif kind == 'CODE_REVIEW' and payload.get('review_scope') == 'srs_wbs_reconciliation':
        contract = {'approved': False, 'requirements_traced': payload['requirements'],
                    'reconciliation_manifest_sha256': payload['reconciliation_manifest_sha256'],
                    'requirements_checked': [{'requirement_id': 'R1', 'chapter_ids': ['ch01'],
                        'criteria_ids': ['AC1'], 'test_ids': ['T1'], 'wbs_leaf_id': 'L1', 'wbs_leaf_ids': ['L1'],
                        'status': 'SATISFIED', 'rationale': 'Exact code and test evidence showing compliance'}],
                    'divergences': []}
        instruction = ('Before final code approval independently reconcile the implemented code with every supplied SRS chapter, '
                       'WBS leaf, requirement, acceptance criterion and test in reconciliation_manifest. '
                       'Inspect the exact source_context, sealed tests and prior asymmetric review receipts. '
                       'A reviewer from the producing provider cannot approve reconciliation. Do not change files. '
                       'Return one concrete requirement mapping for every assigned requirement and copy the manifest hash exactly. '
                       'When reconciliation_scope is workflow, cover all wbs_leaves and every workflow requirement; otherwise cover the current leaf. '
                       'Sort all chapter, criterion, test and owning wbs_leaf_ids exactly; set wbs_leaf_id to the first owner. '
                       'Approve only if every requirement is satisfied and there are no divergences. '
                       'If code, planning or requirements diverged, set approved false and describe every divergence for remediation.')
    elif kind == 'CODE_REVIEW':
        item = payload['file']
        contract = {'path': item['path'], 'file_sha256': item['after_sha256'], 'diff_sha256': item['diff_sha256'],
                    'test_receipt_sha256': payload['test_receipt_sha256'], 'approved': False, 'objective_satisfied': False,
                    'requirements_traced': payload['requirements'], 'minor_findings':[], 'findings': ['Concrete findings or approval rationale']}
        instruction = ('Review this exact changed file and actual patch against requirements and tests. Do not change any file. '
                       'Inspect the supplied source_context, identify defects or missing behavior, and return a substantiated decision. '
                       'Copy the supplied actual evidence hashes exactly. Your model must differ from the producing model.')
    elif kind == 'CODE_RESEARCH' and payload.get('research_phase')=='initial':
        contract = {'plan_sha256':payload['plan_sha256'],
                    'sources':[{'path':'project/source/or/document','quote':'Exact relevant technical source text'}],
                    'hypothesis':'Constraints grounded in inspected sources','strategy':'Concrete test-first implementation approach'}
        instruction = ('Research implementation constraints before tests or code generation using source_context code and technical documentation; '
                       'cite at least two exact passages from immutable files, identify constraints and select a concrete strategy. '
                       'Bind the dossier to the approved plan. Do not change files or invent external citations.')
    elif kind == 'CODE_RESEARCH':
        contract = {'failure_evidence_sha256': payload['failure_evidence_sha256'],
                    'sources': [{'path': '$test_receipt', 'quote': 'Exact diagnostic text'},
                                {'path': 'project/source/or/document', 'quote': 'Exact relevant technical source text'}],
                    'root_cause': {'category': 'implementation', 'diagnosis': 'Concrete cause supported by the cited evidence'},
                    'disposition': 'pivot',
                    'hypothesis': 'Concrete cause consistent with the evidence',
                    'strategy': 'A changed implementation approach grounded in the inspected sources'}
        instruction = ('Code generation is frozen after three failures. Perform bounded technical research and triage using '
                       'the immutable source_context files/documents and actual test diagnostics. Quote exact supplied passages, '
                       'explain the root cause and choose a changed strategy. Do not alter files. Do not invent external citations. '
                       'Classify root_cause.category as implementation, test_assumption, interface_contract, dependency, '
                       'environment, requirements, or unknown. Choose disposition pivot for a concrete supported correction '
                       'or escalate when operator action is required. A test_assumption pivot restarts sealed test authoring '
                       'from the current leaf baseline while retaining prior immutable evidence. '
                       'The controller verifies every quotation and binds your dossier to the three failed attempts.')
    elif kind == 'TASK_PLAN':
        from .planning_gateway import prompt_contract
        contract, instruction, payload = prompt_contract(payload)
    else:
        raise ValueError(f'Unsupported executable node kind: {kind}')
    if kind=='CODE_RESEARCH' and payload.get('planning_evidence', {}).get('external_sources'):
        contract['external_sources']=[{'source_id':'registered-source-id','quote':'Exact relevant fetched source passage',
                                      'requirement_ids':['R1']}]
        instruction += (' Cite at least two distinct controller-fetched external_sources in planning_evidence and trace '
                        'all current requirements as R1..Rn. The controller checks source bytes, exact quotes and '
                        'coverage; a self-reported confidence score cannot satisfy the evidence gate.')
    if kind == 'TASK_PLAN' and isinstance(node.get('payload'), dict) and (node['payload'].get('planning_intent') or {}).get('stage') == 'MICROTASK_SWARM_BATCH':
        sbatch = node['payload'].get('swarm_batch') or {}
        instruction += (
            f" STAGE: MICROTASK_SWARM_BATCH (provider_family={sbatch.get('provider_family')}, "
            f"slot_id={sbatch.get('slot_id')}, max_agents_per_slot={sbatch.get('max_agents_per_slot')}, "
            f"max_nesting_depth={sbatch.get('max_nesting_depth')}). "
            "Intra-slot subagent swarm delegation is enabled within the assigned provider slot cap, "
            "with each subagent executing at its microtask's exact routed (model, reasoning_effort) tier. "
            "External MCP servers, hooks, and host shell execution remain disabled."
        )
    else:
        instruction += (' Native tools, MCP servers, hooks, and host execution are disabled. '
                        'Delegation is disabled. All model jobs are assigned by the controller job board; never spawn another agent.')
    if kind in CODING_NATIVE_KINDS:
        instruction += (' '
                        'Use only the supplied source_context file texts and controller diagnostics as project evidence. '
                        'The inventory identifies omitted files; do not claim to have inspected omitted contents or executed tests. '
                        'Only the controller applies file proposals and runs project code in Docker.')
    return contract, instruction, payload


CONTRACT_SCHEMA = 'cochem-output-contract/1'
FEEDBACK_SCHEMA = 'cochem-output-format-feedback/1'
MAX_FORMAT_CORRECTIONS = 2
_ISSUE_CODES = frozenset({'invalid_json', 'missing_field', 'wrong_type', 'unexpected_field'})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


class OutputFormatError(ValueError):
    """Safe formatting diagnosis; no answer content or native output is exposed."""
    def __init__(self, contract_sha256, issues):
        self.contract_sha256 = contract_sha256
        self.issues = tuple(deepcopy(issues[:32]))
        super().__init__('Generated output does not match the supplied JSON format')

    def as_feedback(self):
        return {'schema': FEEDBACK_SCHEMA, 'contract_sha256': self.contract_sha256,
                'issues': deepcopy(list(self.issues))}


def _schema(value, *, path='$', optional=frozenset(), strict=False):
    """The illustrative shape defines types, never fabricated example values."""
    if isinstance(value, dict):
        # These are maps keyed by captured identities, not literal schema fields.
        if path.rsplit('.', 1)[-1] in {'artifact_hashes', 'chapter_hashes', 'chapter_output_hashes',
                                      'wbs_tasks_by_chapter', 'subagent_outputs'}:
            item = next(iter(value.values()), None)
            return {'type': 'object', 'additionalProperties': _schema(item, path=path+'.*',
                    optional=optional, strict=strict) if item is not None else {}}
        return {'type': 'object', 'properties': {key: _schema(item, path=path+'.'+key,
                    optional=optional, strict=strict) for key, item in value.items()},
                'required': [key for key in value if path+'.'+key not in optional],
                'additionalProperties': not strict}
    if isinstance(value, list):
        return {'type': 'array', 'items': _schema(value[0], path=path+'[]', optional=optional,
                                                strict=strict) if value else {}}
    kind = ('boolean' if type(value) is bool else 'integer' if type(value) is int else
            'number' if type(value) is float else 'string' if isinstance(value, str) else 'null')
    return {'type': kind}


def _blank(value):
    if isinstance(value, dict):
        return {key: _blank(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_blank(item) for item in value]
    return None


def _execution_form(requirements, names, criteria):
    return dict(artifact_text=None,
        deliverables=[dict(name=name, content=None, sha256=None) for name in names],
        requirement_evidence=[dict(requirement_id=key, deliverable_name=None,
                                   verification_evidence=None) for key in requirements],
        release_criteria_results=[dict(criterion=key, passed=None, evidence=None) for key in criteria])


def _handoff(node, example):
    payload = node['payload']
    intent = payload.get('planning_intent') or {}
    state = intent.get('task') or {}
    document = state.get('document') or {}
    response = _blank(example)
    fixed = {}

    def bind(key, value):
        if key in response:
            response[key] = deepcopy(value)
            fixed[key] = deepcopy(value)

    # Only facts already committed by the controller may be prefilled.
    for key in ('chapter_id', 'requirements_traced', 'wbs_tasks_defined', 'artifact_uri',
                'chapter_hashes', 'chapter_output_hashes', 'coverage_report_sha256',
                'wbs_tasks_by_chapter', 'plan_sha256', 'artifact_hashes', 'requirements_checked',
                'failure_evidence_sha256', 'reconciliation_manifest_sha256',
                'path', 'file_sha256', 'diff_sha256', 'test_receipt_sha256'):
        if key in example and key not in {'requirements_checked'}:
            # Values in these fields are supplied in output_contract_details,
            # never the placeholder examples for proposed plans/research.
            bind(key, example[key])
    if node['kind'] == 'CODE_PLAN_REVIEW':
        bind('requirements_checked', example['requirements_checked'])
    stage = intent.get('stage')
    micro = payload.get('microtask_node') or {}
    if stage in ('SIMPLE_EXECUTION', 'MICROTASK_EXECUTION'):
        requirements = (micro.get('requirement_ids', []) if micro else
                        [item['id'] for item in document.get('requirements', [])])
        criteria = micro.get('release_criteria', []) if micro else document.get('release_criteria', [])
        names = micro.get('deliverables', []) if micro else []
        response.update(_execution_form(requirements, names, criteria))
        fixed.update(requirement_ids=requirements, release_criteria=criteria, deliverable_names=names)
    if stage == 'MICROTASK_ASSESSMENT':
        response['assessments'] = [dict(id=item['id'], complexity=None, task_types=[], rationale=None)
                                   for item in state.get('microtasks', [])]
    if stage == 'MICROTASK_SWARM_BATCH':
        batch = payload.get('swarm_batch') or payload.get('microtask_batch') or {}
        for key in ('batch_id', 'provider_family'):
            if key in batch:
                bind(key, batch[key])
        members = {item['microtask_id']: item for item in batch.get('subagents', [])}
        response['subagent_outputs'] = {key: _execution_form(
            members.get(key, {}).get('requirement_ids', []),
            members.get(key, {}).get('deliverables', []),
            members.get(key, {}).get('release_criteria', [])) for key in batch.get('microtask_ids', [])}
    context = {key: deepcopy(payload[key]) for key in
        ('objective', 'requirements', 'allowed_paths', 'test_paths', 'active_leaf',
         'source_context_sha256', 'test_receipt_sha256', 'plan_sha256') if key in payload}
    for key in ('task_id', 'microtask_id', 'complexity', 'task_types', 'srs_sha256',
                'plan_generation_sha256', 'predecessor_artifact_hashes'):
        if key in intent:
            context[key] = deepcopy(intent[key])
    if document:
        context['requirements'] = deepcopy(document.get('requirements', []))
        context['release_criteria'] = deepcopy(document.get('release_criteria', []))
    if micro:
        context['microtask'] = deepcopy(micro)
    return dict(schema='cochem-job-handoff/1', job_kind=node['kind'],
                identities={key: node[key] for key in ('job_id', 'workflow_id') if key in node},
                assignment=context, fixed_bindings=fixed, response=response,
                unfilled_values='null entries require substantive work except explicitly controller-derived digests; this form is not a completion')


def prepare_output_contract(node):
    """Pure preparation: no providers, filesystem, secrets or invented evidence."""
    example, instruction, payload = output_contract_details(node)
    kind = node['kind']
    stage = (node['payload'].get('planning_intent') or {}).get('stage')
    generates_deliverables = kind == 'TASK_PLAN' and stage in {
        'SIMPLE_EXECUTION', 'MICROTASK_EXECUTION', 'MICROTASK_SWARM_BATCH'}
    if generates_deliverables:
        def clear_example_digest(value):
            if isinstance(value, dict):
                if set(value) == {'name', 'content', 'sha256'}:
                    value['sha256'] = None
                for child in value.values():
                    clear_example_digest(child)
            elif isinstance(value, list):
                for child in value:
                    clear_example_digest(child)
        clear_example_digest(example)
        instruction += (' For newly generated deliverables, omit sha256 or return null; '
                        'the controller computes that digest from the exact UTF-8 content before validation. '
                        'A supplied non-null digest must be correct and will not be repaired. '
                        'Copy upstream and evidence hashes exactly; they are never regenerated from claims.')
    optional = {'$.summary'}
    if kind == 'CHAPTER_DRAFT':
        optional.add('$.wbs_tasks_defined')  # controller reconciliation restores it
    if kind == 'CODE_TEST_AUTHOR':
        optional.add('$.reuse_tests')
    if kind == 'CODE_EDIT':
        optional.update({'$.artifact_blocks', '$.remaining_work'})  # P9 can legitimately have no changes
    if kind == 'CODE_REVIEW':
        optional.add('$.minor_findings')
    if kind == 'CODE_RESEARCH':
        optional.add('$.hypothesis')
    if kind == 'CODE_PLAN':
        optional.update({'$.leaves[].dependencies', '$.leaves[].estimated_added_deleted_lines',
                         '$.leaves[].estimated_context_lines'})  # legacy size spelling remains supported
    schema = _schema(example, optional=optional, strict=kind in {'TASK_PLAN', 'PREFLIGHT_REQUEST'})
    if generates_deliverables:
        def allow_derived_digest(spec):
            if isinstance(spec, dict):
                properties = spec.get('properties', {})
                if set(properties) == {'name', 'content', 'sha256'}:
                    properties['sha256'] = {'anyOf': [{'type': 'string'}, {'type': 'null'}]}
                    spec['required'].remove('sha256')
                for child in spec.values():
                    allow_derived_digest(child)
            elif isinstance(spec, list):
                for child in spec:
                    allow_derived_digest(child)
        allow_derived_digest(schema)
    if kind == 'TASK_PLAN' and stage == 'MICROTASK_SWARM_BATCH':
        # Preserve the semantic validator's accepted map/list forms, while the
        # initial handoff supplies the preferred explicit envelope.
        outputs = schema['properties']['subagent_outputs']
        schema['properties']['subagent_outputs'] = {'anyOf': [outputs, {'type': 'array', 'items': {'type': 'object'}}]}
        schema['required'] = ['subagent_outputs']
        schema['additionalProperties'] = True
        schema = {'anyOf': [schema, {'type': 'object', 'additionalProperties': {'type': 'object'}}]}
    handoff = _handoff(node, example)
    contract = dict(schema=CONTRACT_SCHEMA, kind=kind, output_schema=schema, handoff=handoff)
    return dict(contract, contract_sha256=_digest(contract), example=example,
                instruction=instruction, task_payload=payload)


def validate_output_format(node, output):
    """Classify only syntactic/structural mistakes; all semantics stay separate."""
    prepared = prepare_output_contract(node)
    issues = []

    def visit(value, spec, path):
        if len(issues) >= 32 or not spec:
            return
        if 'anyOf' in spec:
            previous = list(issues)
            for alternative in spec['anyOf']:
                issues[:] = previous
                visit(value, alternative, path)
                if issues == previous:
                    return
            issues[:] = previous + [dict(path=path, code='wrong_type')]
            return
        expected = spec['type']
        valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
                 'boolean': type(value) is bool, 'integer': type(value) is int,
                 'number': type(value) in (int, float), 'string': isinstance(value, str),
                 'null': value is None}[expected]
        if not valid:
            issues.append(dict(path=path, code='wrong_type'))
            return
        if expected == 'object':
            properties = spec.get('properties', {})
            for key in spec.get('required', []):
                if key not in value:
                    issues.append(dict(path=path+'.'+key, code='missing_field'))
            for key, child in properties.items():
                if key in value:
                    visit(value[key], child, path+'.'+key)
            extra = spec.get('additionalProperties')
            if extra is False and set(value)-set(properties):
                issues.append(dict(path=path, code='unexpected_field'))
            elif isinstance(extra, dict):
                for child in value.values():
                    visit(child, extra, path+'.*')
        elif expected == 'array':
            for child in value:
                visit(child, spec['items'], path+'[]')
    visit(output, prepared['output_schema'], '$')
    if issues:
        raise OutputFormatError(prepared['contract_sha256'], issues)


def invalid_json_output(node):
    return OutputFormatError(prepare_output_contract(node)['contract_sha256'],
                             [dict(path='$', code='invalid_json')])


def normalize_generated_output(node, output):
    """Fill only omitted/null new-content digests; preserve every supplied claim.

    Existing semantic validators still verify hashes, requirement coverage and
    release results. An invalid supplied hash is never fixed. Raw and normalized
    object digests make this deterministic formatting step auditable.
    """
    stage = (node['payload'].get('planning_intent') or {}).get('stage')
    if node['kind'] != 'TASK_PLAN' or stage not in {
            'SIMPLE_EXECUTION', 'MICROTASK_EXECUTION', 'MICROTASK_SWARM_BATCH'}:
        return output, None
    normalized, changes = deepcopy(output), []

    def fill(answer, path):
        if not isinstance(answer, dict) or not isinstance(answer.get('deliverables'), list):
            return
        for index, item in enumerate(answer['deliverables']):
            if (isinstance(item, dict) and item.get('sha256') is None
                    and isinstance(item.get('content'), str)):
                item['sha256'] = hashlib.sha256(item['content'].encode('utf-8')).hexdigest()
                changes.append(dict(path=path+'.deliverables['+str(index)+'].sha256',
                                    sha256=item['sha256']))
    if stage != 'MICROTASK_SWARM_BATCH':
        fill(normalized, '$')
    elif isinstance(normalized, dict):
        members = normalized.get('subagent_outputs', normalized)
        if isinstance(members, dict):
            for index, answer in enumerate(members.values()):
                fill(answer, '$.subagent_outputs.member['+str(index)+']')
        elif isinstance(members, list):
            for index, answer in enumerate(members):
                if isinstance(answer, dict):
                    fill(answer.get('output', answer), '$.subagent_outputs['+str(index)+']')
    if not changes:
        return output, None
    return normalized, dict(schema='cochem-generated-output-normalization/1',
        operation='fill_missing_new_content_sha256', model_output_sha256=_digest(output),
        accepted_output_sha256=_digest(normalized), changes=changes)


def format_feedback_text(node, contract_sha256):
    feedback = node.get('output_format_feedback')
    if feedback is None:
        return ''
    if (not isinstance(feedback, dict) or feedback.get('schema') != FEEDBACK_SCHEMA
            or feedback.get('contract_sha256') != contract_sha256
            or type(feedback.get('correction_attempt')) is not int
            or not 1 <= feedback['correction_attempt'] <= MAX_FORMAT_CORRECTIONS
            or not isinstance(feedback.get('issues'), list) or not 1 <= len(feedback['issues']) <= 32
            or any(not isinstance(item, dict) or set(item) != {'path', 'code'}
                   or item['code'] not in _ISSUE_CODES or not isinstance(item['path'], str)
                   or not item['path'].startswith('$') or len(item['path']) > 300
                   for item in feedback['issues'])):
        raise ValueError('Controller output format feedback is invalid or belongs to a different contract')
    return ('\n\nCorrect the previous response format using the same assignment and contract. '
            'This is correction ' + str(feedback['correction_attempt']) + ' of at most 2. '
            'Return the complete real answer, not a patch or explanation. '
            'All semantic, identity, dispatch, time and quota requirements still apply.\n'
            + json.dumps(feedback, ensure_ascii=False))
