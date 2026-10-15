"""Independent content review bound to physically verified artifact bytes.

Content review is a model judgment, not an executed code test or proof that an
external action happened. The controller verifies citations into the actual
artifact, exact requirement coverage, a different model family and native
cleanup before accepting the judgment. No reviewer-provided identity is trusted.
"""
from __future__ import annotations

from copy import deepcopy
import json

from . import routing_store as routes
from .task_routing import digest, five_model_options


def review_contract(payload):
    binding = payload['content_review']
    return dict(
        review_binding_sha256=digest(binding), accepted=False,
        requirements=[dict(requirement_id=r['id'], satisfied=False,
                           artifact_path='artifact.txt', excerpt='Exact supporting artifact text',
                           assessment='Explain whether the artifact meets this requirement')
                      for r in binding['requirements']],
        criteria=[dict(criterion=c, satisfied=False, assessment='Explain the observed result')
                  for c in binding['release_criteria']],
        findings=['Actionable remaining defect, or an empty list when accepted'])


def validate_content_review(payload, output, model):
    binding = payload['content_review']
    intent = payload['planning_intent']
    if (model['family'] in binding['producer_families']
            or intent['complexity'] != binding['review_tier']
            or (intent['complexity'] == 10 and model['effort'] !=
                ('high' if model['provider'] == 'gemini' else 'max'))):
        raise ValueError('Content review must use an independent model at the captured reasoning floor')
    expected = {'review_binding_sha256', 'accepted', 'requirements', 'criteria', 'findings'}
    if (not isinstance(output, dict) or set(output) != expected
            or output['review_binding_sha256'] != digest(binding)
            or type(output['accepted']) is not bool):
        raise ValueError('Content review commitment or shape differs')
    from .workflow_428 import _text
    required = {r['id'] for r in binding['requirements']}
    seen = set()
    if not isinstance(output['requirements'], list) or len(output['requirements']) != len(required):
        raise ValueError('Content review must inspect every bound requirement')
    for item in output['requirements']:
        if (not isinstance(item, dict) or set(item) !=
                {'requirement_id', 'satisfied', 'artifact_path', 'excerpt', 'assessment'}
                or item['requirement_id'] not in required or item['requirement_id'] in seen
                or type(item['satisfied']) is not bool):
            raise ValueError('Content review requirement identity differs')
        seen.add(item['requirement_id'])
        _text(item['assessment'], 'Content assessment', 4000)
        # A negative verdict can identify a missing artifact. A positive one
        # must cite bytes actually captured, never a fabricated file or quote.
        if item['satisfied']:
            content = binding['artifacts'].get(item['artifact_path'])
            quote = _text(item['excerpt'], 'Artifact excerpt', 4000)
            if not isinstance(content, str) or quote not in content:
                raise ValueError('Content review cites text absent from the captured artifact')
        elif (not isinstance(item['excerpt'], str) or len(item['excerpt']) > 4000
              or not isinstance(item['artifact_path'], str) or len(item['artifact_path']) > 256):
            raise ValueError('Content review evidence must be text')
    criteria = binding['release_criteria']
    seen = set()
    if not isinstance(output['criteria'], list) or len(output['criteria']) != len(criteria):
        raise ValueError('Content review must inspect every release criterion')
    for item in output['criteria']:
        if (not isinstance(item, dict) or set(item) != {'criterion', 'satisfied', 'assessment'}
                or item['criterion'] not in criteria or item['criterion'] in seen
                or type(item['satisfied']) is not bool):
            raise ValueError('Content review criterion identity differs')
        seen.add(item['criterion'])
        _text(item['assessment'], 'Criterion assessment', 4000)
    if not isinstance(output['findings'], list) or len(output['findings']) > 100:
        raise ValueError('Content findings must be a bounded list')
    for finding in output['findings']:
        _text(finding, 'Content finding', 4000)
    if output['accepted'] and (output['findings'] or not all(
            item['satisfied'] for item in output['requirements'] + output['criteria'])):
        raise ValueError('Accepted content review cannot contain unsatisfied requirements or findings')


class ContentReviewRuntime:
    def __init__(self, journal, store):
        self.journal, self.store = journal, store

    def ensure(self, task_id, *, state, generation, producers, physical):
        """Queue once; then return only committed, cleaned independent review.

        All bindings come from controller custody and the journal. This is not
        an agent/public endpoint and accepts no proposed native route.
        """
        from .planning_gateway import PlanningGateway, prompt_contract, scoped_policy
        with self.journal._write() as conn:
            row = self.journal._read(conn, task_id)
            if json.loads(row['state_json']) != state:
                raise ValueError('Content review source state changed')
            catalog, limit = json.loads(row['catalog_json']), row['flash_context_limit']
            version = row['version']
        if (physical.get('status') != 'VERIFIED'
                or physical.get('output', {}).get('verification_kind') != 'artifact_integrity'):
            raise ValueError('Content review requires completed physical integrity verification')
        verifier = self.store.get(physical['job_id'])
        if (verifier['kind'] != 'TASK_VERIFY' or verifier['status'] != 'COMPLETED'
                or verifier['output'] != physical['output']
                or verifier['payload']['task_id'] != task_id
                or verifier['payload']['source_snapshot_sha256'] != physical['source_snapshot_sha256']):
            raise ValueError('Content review physical verification binding differs')
        families, bindings = set(), []
        for job_id in sorted(set(producers)):
            job = self.store.get(job_id)
            result = PlanningGateway(self.journal, self.store).model_result(job_id)
            if result is None or job['payload']['planning_intent']['task_id'] != task_id:
                raise ValueError('Content producer has no cleaned committed completion')
            family = job['payload']['task_catalog']['models'][result['profile_id']]['family']
            families.add(family)
            bindings.append(dict(job_id=job_id, output_sha256=digest(job['output']),
                                 attempt_id=job['attempt_id'], fencing_token=job['fencing_token']))
        if not families:
            raise ValueError('Content review needs a producer to remain independent')
        files = self.store.coding_files(physical['source_snapshot_sha256'])
        artifacts = {path: value.decode('utf-8') for path, value in sorted(files.items())}
        tier = min(10, state['assessment']['complexity'] + 1)
        options = five_model_options(catalog, state['assessment']['task_types'], tier)
        candidates = [o['model_id'] for o in options if o['meets_floor']
                      and catalog['models'][o['model_id']]['family'] not in families
                      and (tier != 10 or catalog['models'][o['model_id']]['effort'] ==
                           ('high' if catalog['models'][o['model_id']]['provider'] == 'gemini' else 'max'))]
        if not candidates:
            return dict(status='WAITING_FOR_INDEPENDENT_CONTENT_REVIEW_CAPACITY')
        binding = dict(task_id=task_id, plan_generation_sha256=generation,
                       srs_sha256=state['srs_sha256'], source_snapshot_sha256=physical['source_snapshot_sha256'],
                       physical_job_id=physical['job_id'], physical_output_sha256=digest(physical['output']),
                       producer_families=sorted(families), producers=bindings, review_tier=tier,
                       requirements=deepcopy(state['document']['requirements']),
                       release_criteria=deepcopy(state['document']['release_criteria']), artifacts=artifacts)
        intent = dict(schema='cochem-planning-intent/4.2.8', action='model_stage', stage='CONTENT_REVIEW',
                      task_id=task_id, version=version, state_sha256=digest(state), task=state,
                      catalog_sha256=digest(catalog), srs_sha256=state['srs_sha256'], complexity=tier,
                      task_types=state['assessment']['task_types'], candidate_profiles=candidates,
                      content_binding_sha256=digest(binding))
        payload = dict(workflow_type='planning428', planning_intent=intent, task_catalog=catalog,
                       flash_context_limit=limit, content_review=binding)
        prompt_contract(payload)
        key = digest(payload)
        root_id, job_id = 'content428-' + key[:40], 'content428-node-' + key[:40]
        with self.store._write() as conn:
            old = conn.execute('SELECT 1 FROM pipeline_jobs WHERE job_id=?', (job_id,)).fetchone()
            if old is None:
                self.store._insert(conn, root_id, root_id, None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS',
                                   dict(workflow_type='planning428', task_id=task_id))
                routes.capture_workflow(conn, root_id, scoped_policy(self.store.routing_policy, intent, catalog))
                self.store._insert(conn, job_id, root_id, root_id, 'TASK_PLAN', 'PENDING', payload, max_attempts=10)
            job = self.store._get(conn, job_id)
            if job['payload'] != payload:
                raise ValueError('Existing content review has different immutable input')
        result = PlanningGateway(self.journal, self.store).model_result(job_id)
        if result is None:
            return dict(status='CONTENT_REVIEW_HELD' if job['status'] in ('FAILED', 'BLOCKED')
                        else 'WAITING_FOR_INDEPENDENT_CONTENT_REVIEW', job_id=job_id)
        if not result['output']['accepted']:
            return dict(status='CONTENT_REVIEW_REJECTED', job_id=job_id, findings=result['output']['findings'])
        return dict(status='VERIFIED', job_id=job_id,
                    evidence=dict(kind='independent_model_content_review', profile_id=result['profile_id'],
                                  job_id=job_id, output_sha256=digest(result['output']),
                                  physical_job_id=physical['job_id'], binding_sha256=digest(binding),
                                  reviewed_requirements=sorted(r['id'] for r in binding['requirements']),
                                  external_actions_verified=False, code_tests_executed=False))
