"""Bridge validated planning intents onto the existing Chapter 06 job board.

No second worker pool or native runner. Queueing and importing are controller
operations, not public agent tools. Current admission still skips unavailable
or unaccepted profiles; installing this source does not activate a catalog.
"""
from copy import deepcopy
import json

from . import routing_store as routes
from .routing import load_routing_policy
from .task_routing import digest
from .workflow_428 import accept_srs, accept_wbs, accept_microtasks, accept_review


def scoped_policy(base_policy, intent, catalog):
    if (intent.get('action') != 'model_stage' or intent.get('schema') != 'cochem-planning-intent/4.2.8'
            or intent.get('catalog_sha256') != digest(catalog)):
        raise ValueError('Only a captured planning model intent can be queued')
    targets = []
    for key in intent['candidate_profiles'][:5]:
        model = catalog['models'][key]
        target = dict(provider=model['provider'], model=model['model'], reasoning_effort=model['effort'])
        if target not in targets:
            targets.append(target)
    if not targets:
        raise ValueError('No eligible planning targets')
    value = load_routing_policy(base_policy.as_dict() if hasattr(base_policy, 'as_dict') else base_policy).as_dict()
    # Per-node capture uses the same ordered candidates whichever lexical score
    # is projected by an older status client. ensure_job records the actual
    # journal-assigned tier, and native route verification checks that score.
    captured = dict(schema='cochem-routing-catalog/3', generation='planning428-'+digest(intent)[:32],
                    tiers={str(i):deepcopy(targets) for i in range(1,11)})
    keys = {f"{x['provider']}:{x['model']}:{x['reasoning_effort']}" for x in targets}
    value.update(policy_version=3, catalog=captured, tiers=captured['tiers'],
                 model_limits={key:value['model_limits'].get(key) for key in sorted(keys)})
    return load_routing_policy(value).as_dict()


def validate_stage_output(payload, output, route):
    """Semantic validation runs before JobStore accepts a planning completion."""
    intent, catalog = payload['planning_intent'], payload['task_catalog']
    if intent['catalog_sha256'] != digest(catalog) or intent['state_sha256'] != digest(intent['task']):
        raise ValueError('Planning payload commitment differs')
    matches = [key for key in intent['candidate_profiles'] if all(
        catalog['models'][key][left] == route[right] for left,right in
        (('provider','provider'),('model','model'),('effort','reasoning_effort')))]
    if len(matches) != 1:
        raise ValueError('Planning output does not belong to an eligible exact profile')
    state, stage = intent['task'], intent['stage']
    model = catalog['models'][matches[0]]
    if stage in ('SRS','REVISING_SRS'):
        accept_srs(state, output, planner_model=model['family'], flash_context_limit=payload['flash_context_limit'])
    elif stage == 'PLAN_REVIEW':
        if set(output) != {'accepted','findings','suggestions','clarifications'}:
            raise ValueError('Invalid planning review shape')
        from .workflow_428 import _text
        for key in ('findings','suggestions','clarifications'):
            if not isinstance(output[key],list) or len(output[key])>100:
                raise ValueError('Review statements must be bounded arrays')
            for text in output[key]:
                _text(text,'Review statement')
        accept_review(state, reviewer_model=model['family'], reviewer_tier=intent['complexity'],
                      effort=model['effort'], accepted=output['accepted'], review_sha256=digest(output))
    elif stage == 'WBS' and set(output)=={'wbs'}:
        accept_wbs(state,output['wbs'])
    elif stage == 'MICROTASKS' and set(output)=={'microtasks'}:
        accept_microtasks(state,output['microtasks'])
    elif stage == 'MICROTASK_ASSESSMENT':
        from .planning_journal import PlanningJournal
        PlanningJournal._accept_micro_assessments(state,output)
    elif stage == 'SIMPLE_EXECUTION':
        from .task_execution_428 import validate_simple_execution_output
        validate_simple_execution_output(state, output)
    elif stage == 'MICROTASK_EXECUTION':
        from .microtask_board_428 import validate_microtask_execution_output
        validate_microtask_execution_output(payload['microtask_node'], output)
    elif stage == 'MICROTASK_SWARM_BATCH':
        from .swarm_batch_428 import validate_swarm_batch_stage_output
        batch_desc = payload.get('swarm_batch') or payload.get('microtask_batch')
        validate_swarm_batch_stage_output(batch_desc, output)
    else:
        raise ValueError('Unsupported planning output stage')
    return matches[0]


class PlanningGateway:
    def __init__(self, journal, store):
        self.journal, self.store = journal, store

    def submit(self, task_id):
        # Re-read from the durable journal. Never accept an agent-supplied
        # candidate list, complexity, approval, intent or catalog here.
        with self.journal._write() as conn:
            row = self.journal._read(conn,task_id)
            intent = self.journal._intent(row)
            catalog=json.loads(row['catalog_json'])
            limit=row['flash_context_limit']
        policy=scoped_policy(self.store.routing_policy,intent,catalog)
        identity=digest(intent)
        root_id='plan428-'+identity[:40]
        job_id='plan428-node-'+identity[:40]
        payload=dict(workflow_type='planning428', planning_intent=intent,
                     task_catalog=catalog, flash_context_limit=limit)
        prompt_contract(payload)
        with self.store._write() as conn:
            existing=conn.execute('SELECT job_id FROM pipeline_jobs WHERE job_id=?',(job_id,)).fetchone()
            if existing:
                prior=self.store._get(conn,job_id)
                if prior['payload']!=payload:
                    raise ValueError('Existing planning job has different immutable input')
                return prior
            self.store._insert(conn,root_id,root_id,None,'MACRO_PLANNING_REQUEST','IN_PROGRESS',
                               dict(workflow_type='planning428',intent_sha256=identity))
            routes.capture_workflow(conn,root_id,policy)
            self.store._insert(conn,job_id,root_id,root_id,'TASK_PLAN','PENDING',payload,max_attempts=10)
            self.store._event(conn,self.store._get(conn,root_id),'PLANNING_INTENT_SUBMITTED',
                              task_id=task_id,intent_sha256=identity)
            return self.store._get(conn,job_id)

    def model_result(self, job_id):
        """Evidence port reads committed native route, result and cleanup rows."""
        with self.store._connection() as conn:
            job=self.store._get(conn,job_id)
            if job['kind']!='TASK_PLAN' or job['status']!='COMPLETED':
                return None
            cleanup=conn.execute('SELECT cleared_at FROM pipeline_execution_cleanup '
                'WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                (job_id,job['attempt_id'],job['fencing_token'])).fetchone()
            if cleanup is None or cleanup['cleared_at'] is None:
                return None
            profile=validate_stage_output(job['payload'],job['output'],job['route'])
            return dict(job_id=job_id,intent_sha256=digest(job['payload']['planning_intent']),
                profile_id=profile,status='COMPLETED',cleanup_verified=True,output=job['output'])


def _captured_context_limit(payload, route=None):
    """Return capacity from captured eligible profiles; never change their tier."""
    intent = payload.get('planning_intent') or {}
    catalog = payload.get('task_catalog')
    if not isinstance(catalog, dict):
        if route is not None:
            return None
        return payload.get('flash_context_limit')  # offline, unselected preview
    models = [catalog['models'][key] for key in intent.get('candidate_profiles', [])]
    if route is not None:
        models = [model for model in models if (model['provider'], model['model'], model['effort']) ==
                  (route.get('provider'), route.get('model'), route.get('reasoning_effort'))]
        if len(models) != 1:
            raise ValueError('Context check requires one exact eligible captured profile')
    limits = []
    for model in models:
        limit = model.get('context_limit')
        if type(limit) is not int or limit < 1:
            continue
        flash = payload.get('flash_context_limit')
        if model['provider'] == 'gemini' and 'flash' in model['model'].casefold() and type(flash) is int:
            limit = min(limit, flash)
        limits.append(limit)
    return max(limits) if limits else None


def validate_rendered_prompt_context(node, prompt):
    """Budget the exact schema, handoff, feedback, evidence and baseline bytes.

    UTF-8 byte counting is a conservative token bound. Output capacity is also
    reserved. Failure uses normal context routing; candidate order, complexity
    and reasoning floors remain the immutable captured policy.
    """
    if node.get('kind') != 'TASK_PLAN':
        return None
    payload = node['payload']
    limit = _captured_context_limit(payload, node.get('route'))
    if limit is None:
        if node.get('route') is not None or 'task_catalog' in payload:
            from .failures import ProviderFailure
            raise ProviderFailure('context')
        return None  # a standalone form without execution authority
    document = ((payload.get('planning_intent') or {}).get('task') or {}).get('document') or {}
    declared_input = sum(value if type(value) is int and value >= 0 else 0 for value in
                         (document.get('srs_tokens'), document.get('evidence_and_instruction_tokens')))
    reserve = document.get('output_reserve_tokens', 4096)
    reserve = max(4096, reserve) if type(reserve) is int else 4096
    prompt_bytes = len(prompt.encode('utf-8'))
    input_budget = max(prompt_bytes, declared_input)
    if input_budget + reserve > limit:
        from .failures import ProviderFailure
        raise ProviderFailure('context')
    return dict(rendered_prompt_bytes=prompt_bytes, input_budget=input_budget,
                output_reserve=reserve, captured_context_limit=limit)


def prompt_contract(payload, *, check_context=True):
    intent=payload['planning_intent']
    stage=intent['stage']
    task_state=intent['task']
    if isinstance(task_state, dict) and isinstance(task_state.get('research'), dict):
        if task_state['research'].get('srs_sha256') != task_state.get('srs_sha256'):
            raise ValueError('Research evidence belongs to a stale SRS revision')
        if 'research_excerpts' in task_state:
            from .research_evidence_428 import validate_research_excerpts
            validate_research_excerpts(task_state['research']['channels'], task_state['research_excerpts'])
            limit = _captured_context_limit(payload)
            if check_context and limit is not None:
                from .task_routing import context_fits
                doc = task_state.get('document') or {}
                content_budget = max(int(doc.get('srs_tokens', 0)), len(json.dumps(doc, ensure_ascii=False).encode('utf-8')))
                excerpt_bytes = len(json.dumps(task_state['research_excerpts'], ensure_ascii=False).encode('utf-8'))
                instr_budget = max(int(doc.get('evidence_and_instruction_tokens', 0)),
                                   4096 + len(str(task_state.get('objective', '')).encode('utf-8')) + excerpt_bytes)
                out_budget = max(int(doc.get('output_reserve_tokens', 4096)), 4096)
                if not context_fits(content_budget, instr_budget, out_budget, limit):
                    raise ValueError('Research and prompt context exceed verified model context budget')
    if stage in ('SRS','REVISING_SRS'):
        contract=dict(plan='Concrete implementation plan',architecture='Components, interfaces and tradeoffs',
            srs=[dict(id='S1',requirement_ids=['R1'],text='Verifiable specification')],
            requirements=[dict(id='R1',text='Requested behavior')],
            assessment=dict(complexity=1,task_types=['COD-TERM'],rationale='Evidence-based complexity and type assessment'),
            release_criteria=['Objective acceptance checks'],srs_tokens=1,
            evidence_and_instruction_tokens=1,output_reserve_tokens=4096)
    elif stage=='PLAN_REVIEW':
        contract=dict(accepted=False,findings=['Concrete supported issue'],
                      suggestions=['Specific improvement'],clarifications=[])
    elif stage=='WBS':
        contract=dict(wbs=[dict(id='W1',section_ids=['S1'],requirement_ids=['R1'],
            deliverables=['Named artifact'],audit_metrics=['Measurable verification'],release_criteria=['Pass condition'],depends_on=[])])
    elif stage=='MICROTASKS':
        contract=dict(microtasks=[dict(id='M1',wbs_ids=['W1'],role='implementation',complexity=2,
            task_types=['COD-TERM'],deliverables=['Named artifact'],audit_metrics=['Verification'],
            release_criteria=['Pass condition'],depends_on=[],prompt='Self-contained bounded task')])
    elif stage=='MICROTASK_ASSESSMENT':
        contract=dict(assessments=[dict(id='M1',complexity=2,task_types=['COD-TERM'],rationale='Task-specific assessment')])
    elif stage in ('SIMPLE_EXECUTION','MICROTASK_EXECUTION'):
        contract=dict(
            artifact_text='Complete verified deliverable summary',
            deliverables=[dict(name='artifact.txt',content='Deliverable content',sha256='0'*64)],
            requirement_evidence=[dict(requirement_id='R1',deliverable_name='artifact.txt',verification_evidence='Exact check')],
            release_criteria_results=[dict(criterion='Criterion',passed=True,evidence='Exact verification')]
        )
    elif stage == 'MICROTASK_SWARM_BATCH':
        batch_meta = payload.get('swarm_batch') or payload.get('microtask_batch') or {}
        contract = dict(
            batch_id=batch_meta.get('batch_id', 'swbatch428-1'),
            provider_family=batch_meta.get('provider_family', 'claude'),
            subagent_outputs={
                'M1': dict(
                    artifact_text='Complete verified deliverable summary',
                    deliverables=[dict(name='artifact.txt', content='Deliverable content', sha256='0' * 64)],
                    requirement_evidence=[dict(requirement_id='R1', deliverable_name='artifact.txt', verification_evidence='Exact check')],
                    release_criteria_results=[dict(criterion='Criterion', passed=True, evidence='Exact verification')],
                )
            },
        )
    else:
        raise ValueError('Stage is not a native planning request')
    instruction=('Produce the specified planning artifact using the captured requirements and research. '
        'Do not execute code or assert that tests, searches or human approvals occurred. '
        'A review accepts only a sound plan; reject material defects and supply actionable corrections. '
        'WBS must cover every requirement. Microtasks need implementation, assembly and final-test nodes; '
        'assembly follows all fragments and final testing follows assembly. Preserve WBS dependencies. '
        'Aim for single-type complexity 1–5 implementation fragments; assess orchestration and assembly honestly.')
    return contract,instruction,task_state
