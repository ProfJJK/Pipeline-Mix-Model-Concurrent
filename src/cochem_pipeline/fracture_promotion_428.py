"""Controller-owned promotion of whole-task failure into a reviewed fracture.

Normal WBS materialization would create fresh quality roots. A promotion instead
retains its exact failed source and ten/twenty boundary through SRS gates, then
uses the registered fracture graph directly. It never invents output paths.
"""
from copy import deepcopy
import json

from .task_routing import digest
from .workflow_428 import _id, assessment


def begin_promotion(journal, task_id, boundary, source, pivot_job, pivot_result, ledger, dossier):
    intent = source['payload']['planning_intent']
    root, number = boundary['lineage_root'], boundary['boundary']
    classification = assessment(pivot_result['output']['assessment'])
    binding = dict(schema='cochem-whole-fracture-promotion/4.2.8', lineage_root=root,
        boundary=number, source_job_id=source['job_id'], source_intent_sha256=digest(intent),
        pivot_result_sha256=digest(pivot_result),
        dossier_sha256=pivot_job['payload']['planning_intent']['failure_dossier_sha256'])
    current = journal.status(task_id)
    existing = current.get('fracture_promotion')
    if existing:
        if any(existing.get(key) != value for key, value in binding.items()):
            raise ValueError('Whole-task promotion cannot be rebound')
        return current
    if (source['payload'].get('microtask_node') or number not in (10, 20)
            or ledger.get('root') != root or ledger.get('failures') != number
            or ledger.get('stage') != 'PIVOT_RESEARCH' or not ledger.get('research_due')
            or not dossier or dossier.get('research_complete') is not True
            or dossier['dossier_sha256'] != binding['dossier_sha256']
            or intent['task_id'] != task_id or pivot_result['output']['strategy'] != 'fracture'):
        raise ValueError('Whole-task promotion needs its researched original failure boundary')
    minimum = max(classification['complexity'], min(10, ledger['floor'] + 1))
    classification = dict(classification, complexity=minimum)
    def transition(row):
        state = json.loads(row['state_json'])
        if state['stage'] == 'CANCELLED' or digest(state) != intent['state_sha256']:
            raise ValueError('Whole-task promotion belongs to a stale source capture')
        original = state.get('document') or {}
        promotion = dict(binding, minimum_complexity=minimum,
            original_requirements=deepcopy(original.get('requirements', [])),
            original_release_criteria=deepcopy(original.get('release_criteria', [])),
            control_lineage='promotion428-' + digest(binding)[:40])
        updated = deepcopy(state)
        updated.update(stage='REVISING_SRS', fracture_promotion=promotion,
            assessment=classification, pivot_reasoning_floor=minimum,
            planning_attempt_lineage_id=promotion['control_lineage'],
            review=None, research=None, approval=None,
            failure_dossier=deepcopy(dossier),
            fracture_recommendation=deepcopy(pivot_result['output']))
        for key in ('planning_pivot_routes', 'execution_pivot', 'promoted_fracture'):
            updated.pop(key, None)
        return updated
    return journal._transition(task_id, current['journal_version'],
        'promotion.' + digest(binding)[:40], binding, transition)


def validate_promoted_srs(state, document):
    promotion = state.get('fracture_promotion')
    if not promotion:
        return
    if document['assessment']['complexity'] < promotion['minimum_complexity']:
        raise ValueError('Promoted SRS cannot lower its retained reasoning floor')
    requirements = {row['id']: row['text'] for row in document['requirements']}
    if (any(requirements.get(row['id']) != row['text'] for row in promotion['original_requirements'])
            or not set(promotion['original_release_criteria']) <= set(document['release_criteria'])
            or not set(state.get('requested_requirements', [])) <= set(requirements.values())):
        raise ValueError('Promoted SRS must preserve exact original requirements and release criteria')


def promotion_scope(state, ledger):
    if state.get('stage') != 'FRACTURE_PROMOTION_READY' or not state.get('fracture_promotion'):
        raise ValueError('Whole fracture requires completed SRS, review and WBS gates')
    promotion = state['fracture_promotion']
    if (ledger['root'] != promotion['lineage_root'] or ledger['failures'] != promotion['boundary']
            or ledger['stage'] != 'PIVOT_RESEARCH' or not ledger['research_due']
            or state.get('review', {}).get('srs_sha256') != state['srs_sha256']
            or state.get('research', {}).get('srs_sha256') != state['srs_sha256']
            or state['approval_required'] and not state.get('approval')):
        raise ValueError('Whole-fracture source gates or original boundary changed')
    paths = sorted({path for row in state['wbs'] for path in row['deliverables']})
    if not paths:
        raise ValueError('Reviewed WBS must define deliverable paths before fracture')
    return dict(scope_id='whole428-' + digest(promotion)[:40], lineage_root=ledger['root'],
        parent_floor=ledger['floor'], last_failed_model=ledger['last_model'],
        minimum_assembly_complexity=state['assessment']['complexity'],
        requirement_ids=[row['id'] for row in state['document']['requirements']],
        deliverables=paths, release_criteria=state['document']['release_criteria'])


def activate_promotion(journal, task_id, record):
    """Project only a controller-registered graph; the board rechecks authority."""
    current = journal.status(task_id)
    binding = dict(fracture_id=record['fracture_id'], graph_sha256=record['graph_sha256'],
        lineage_root=record['lineage_root'], after_failures=record['after_failures'])
    if current.get('promoted_fracture'):
        if current['promoted_fracture'] != binding:
            raise ValueError('Promoted graph cannot be rebound')
        return current
    def transition(row):
        state = json.loads(row['state_json'])
        promotion = state['fracture_promotion']
        if (state['stage'] != 'FRACTURE_PROMOTION_READY'
                or promotion['lineage_root'] != record['lineage_root']
                or promotion['boundary'] != record['after_failures']):
            raise ValueError('Promoted graph belongs to another source boundary')
        children = deepcopy(record['graph']['children'])
        updated = deepcopy(state)
        updated.update(stage='MICROTASKS_READY', promoted_fracture=binding,
            microtasks=children, microtasks_sha256=digest(children))
        return updated
    return journal._transition(task_id, current['journal_version'],
        'promotion-ready.' + digest(binding)[:36], binding, transition)


def compile_promoted_graph(state, record):
    binding = state['promoted_fracture']
    if (state['stage'] != 'MICROTASKS_READY' or any(record[key] != binding[key] for key in binding)
            or digest(state['microtasks']) != state['microtasks_sha256']
            or state['microtasks'] != record['graph']['children']):
        raise ValueError('Promoted graph differs from its registered task capture')
    rows = {row['child_id']: row for row in record['children']}
    context = dict(fracture_id=record['fracture_id'], graph_sha256=record['graph_sha256'],
        dossier_sha256=record['dossier_sha256'], lineage_root=record['lineage_root'],
        failed_microtask_id=record['failed_scope_id'])
    nodes = []
    for child in record['graph']['children']:
        cid = _id(child['id'])
        projection = rows[cid]
        wbs = [row for row in state['wbs'] if set(row['requirement_ids']) & set(child['requirement_ids'])]
        if not wbs:
            raise ValueError('Promoted child lacks reviewed WBS traceability')
        node = {key: deepcopy(value) for key, value in child.items() if key not in ('id', 'lineage_root', 'failed_scope_id')}
        node.update(microtask_id=cid, parent_task_id=state['task_id'], lineage_kind='FAILURE_FRACTURE',
            attempt_lineage_id=cid, fracture_context=context,
            wbs_ids=[row['id'] for row in wbs], section_ids=sorted({sec for row in wbs for sec in row['section_ids']}),
            assessment={key: child[key] for key in ('complexity', 'task_types', 'rationale')},
            needs_owner_approval=projection['needs_owner_approval'], owner_approval=projection['owner_approval'])
        nodes.append(node)
    return nodes
