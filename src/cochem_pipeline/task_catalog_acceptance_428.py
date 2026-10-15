"""Owner-run task catalog acceptance using the existing four shared probe seats.

Importing or preparing a request executes nothing. Only the protected SYSTEM
entrypoint invokes run_acceptance; public APIs cannot publish a task catalog.
Native evidence, cleanup, and publication share the protected board transaction.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import time

from . import catalog_journal, catalog_slots
from .catalog_authority import CatalogAuthority, _WindowsCustody
from .failures import ProviderFailure
from .r6_native_acceptance import make_probe, validate_result
from .routing import _strict_json, load_routing_policy
from .task_catalog_428 import TaskCatalogBindingPlan, compile_task_catalog_plan
from .task_routing import digest


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


@dataclass(frozen=True)
class TaskCatalogRequest:
    request_id: str
    proposal_sha256: str
    plan: TaskCatalogBindingPlan
    execution_bindings: dict
    allow_partial_publication: bool = False

    @property
    def pointer_sha256(self):
        return digest(dict(schema='cochem-task-catalog-pointer/4.2.8',
                           request_id=self.request_id, proposal_sha256=self.proposal_sha256))


def execution_bindings(providers, workers):
    """Sanitized pins cover exact provider/effort/agent configuration, not secrets."""
    from .agy_agent_guard import require_agent_contract
    if not isinstance(providers, dict) or set(providers) != {'codex','claude','gemini'}:
        raise ValueError('Task catalog requires all three protected provider specifications')
    if not isinstance(workers, dict) or set(workers) != {f'slot{i}' for i in range(1,7)}:
        raise ValueError('Task catalog requires all six exact isolated worker profiles')
    agent = require_agent_contract(providers['gemini'])
    return {name: dict(provider_contract_sha256=digest(spec),
                       worker_profiles_sha256=digest(workers),
                       agent_contract_sha256=digest(agent) if name=='gemini' else None)
            for name, spec in providers.items()}


def _check_bindings(bindings):
    if not isinstance(bindings, dict) or set(bindings) != {'codex','claude','gemini'}:
        raise ValueError('Task catalog execution bindings require all providers')
    for name, row in bindings.items():
        if (not isinstance(row, dict) or set(row) != {
                'provider_contract_sha256','agent_contract_sha256','worker_profiles_sha256'}
                or not isinstance(row['provider_contract_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', row['provider_contract_sha256'])
                or not isinstance(row['worker_profiles_sha256'],str)
                or not re.fullmatch('[0-9a-f]{64}',row['worker_profiles_sha256'])
                or (name=='gemini' and (not isinstance(row['agent_contract_sha256'],str)
                    or not re.fullmatch('[0-9a-f]{64}',row['agent_contract_sha256'])))
                or (name!='gemini' and row['agent_contract_sha256'] is not None)):
            raise ValueError('Task catalog execution/agent binding is invalid')
    if len({row['worker_profiles_sha256'] for row in bindings.values()}) != 1:
        raise ValueError('Task catalog provider profile identities disagree')


def prepare_request(policy, catalog, binary_bindings, *, request_id, execution_bindings,
                    previous_task_catalog=None, candidate_profile_ids=None,
                    retired_profile_ids=(), model_limits=None, allow_partial_publication=False):
    """Offline deterministic preparation. Its bytes are not execution authority."""
    if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id):
        raise ValueError('Task catalog request needs a fresh 32-character request ID')
    _check_bindings(execution_bindings)
    if type(allow_partial_publication) is not bool:
        raise ValueError('Explicit partial publication policy required')
    plan = compile_task_catalog_plan(policy, catalog, binary_bindings,
        expected_policy_digest=policy.digest, previous_task_catalog=previous_task_catalog,
        candidate_profile_ids=candidate_profile_ids, retired_profile_ids=retired_profile_ids,
        model_limits=model_limits)
    return dict(schema='cochem-task-catalog-request/4.2.8', request_id=request_id,
                previous_policy_digest=policy.digest,
                previous_task_catalog_sha256=digest(previous_task_catalog) if previous_task_catalog else None,
                catalog=deepcopy(catalog), binary_bindings=deepcopy(binary_bindings),
                candidate_profile_ids=list(plan.selected_profile_ids),
                retired_profile_ids=sorted(retired_profile_ids), model_limits=dict(plan.model_limits),
                plan_digest=plan.digest, execution_bindings=deepcopy(execution_bindings),
                allow_partial_publication=allow_partial_publication, activation_authorized=False)


def decode_request(data, policy, previous_task_catalog, *, expected_sha256):
    if (not isinstance(data, bytes) or not 1 <= len(data) <= 4 * 1024 * 1024
            or hashlib.sha256(data).hexdigest() != expected_sha256):
        raise ValueError('Task catalog request bytes differ from reviewed pin')
    raw = _strict_json(data.decode('utf-8'))
    if not isinstance(raw, dict) or set(raw) != {
            'schema','request_id','previous_policy_digest','previous_task_catalog_sha256',
            'catalog','binary_bindings','candidate_profile_ids','retired_profile_ids',
            'model_limits','plan_digest','execution_bindings','allow_partial_publication','activation_authorized'}:
        raise ValueError('Invalid task catalog request fields')
    if (raw['schema'] != 'cochem-task-catalog-request/4.2.8'
            or raw['activation_authorized'] is not False
            or raw['previous_policy_digest'] != policy.digest
            or raw['previous_task_catalog_sha256'] != (digest(previous_task_catalog) if previous_task_catalog else None)):
        raise ValueError('Task catalog request is stale or claims its own authority')
    rebuilt = prepare_request(policy, raw['catalog'], raw['binary_bindings'],
        request_id=raw['request_id'], previous_task_catalog=previous_task_catalog,
        execution_bindings=raw['execution_bindings'],
        candidate_profile_ids=raw['candidate_profile_ids'], retired_profile_ids=raw['retired_profile_ids'],
        model_limits=raw['model_limits'], allow_partial_publication=raw['allow_partial_publication'])
    if rebuilt != raw:
        raise ValueError('Task catalog request does not match its compiled plan')
    plan = compile_task_catalog_plan(policy, raw['catalog'], raw['binary_bindings'],
        expected_policy_digest=policy.digest, previous_task_catalog=previous_task_catalog,
        candidate_profile_ids=raw['candidate_profile_ids'], retired_profile_ids=raw['retired_profile_ids'],
        model_limits=raw['model_limits'])
    return TaskCatalogRequest(raw['request_id'], expected_sha256, plan, deepcopy(raw['execution_bindings']),
                              raw['allow_partial_publication'])


@contextmanager
def protected_request(path, expected_sha256, policy, previous_task_catalog):
    """Retain protected request custody through all probes and publication."""
    from . import windows
    windows.require_system()
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Protected task catalog request must be absolute')
    backend = _WindowsCustody(windows)
    handles = []
    try:
        for directory in reversed(path.parents):
            handles.append(backend.acquire(directory, True))
            backend.inspect(directory, True)
        handles.append(backend.acquire(path, False))
        size = backend.inspect(path, False)
        backend.validate(path)
        if not 1 <= size <= 4 * 1024 * 1024:
            raise ValueError('Protected task catalog request exceeds its bound')
        data = backend.read(path, size + 1)
        if len(data) != size:
            raise ValueError('Protected task catalog request changed while held')
        yield decode_request(data, policy, previous_task_catalog, expected_sha256=expected_sha256)
    finally:
        for handle in reversed(handles):
            backend.release(handle)


def initialize(conn):
    catalog_slots.initialize(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS pipeline_task_probe_evidence (
        reservation_id TEXT PRIMARY KEY REFERENCES pipeline_catalog_probes(reservation_id),
        request_id TEXT NOT NULL, plan_digest TEXT NOT NULL,
        evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)))''')
    for operation in ('UPDATE','DELETE'):
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS task_probe_no_{operation.lower()}
            BEFORE {operation} ON pipeline_task_probe_evidence
            BEGIN SELECT RAISE(ABORT,'task probe evidence is immutable'); END''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pipeline_task_catalog_holds (
        request_id TEXT NOT NULL, target_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
        PRIMARY KEY(request_id,target_json))''')
    for operation in ('UPDATE','DELETE'):
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS task_catalog_hold_no_{operation.lower()}
            BEFORE {operation} ON pipeline_task_catalog_holds
            BEGIN SELECT RAISE(ABORT,'task catalog hold evidence is immutable'); END''')


def defer_held_target(conn, request, target):
    """Capture an actual scoped board hold; it never invents a native attempt."""
    catalog_journal._transaction(conn)
    if not request.allow_partial_publication:
        return False
    probe_authority(request, target)  # Validates exact request target membership.
    resources = {'model': ':'.join(target), 'provider': target[0],
                 'pool': request.plan.policy.as_dict()['provider_limits'][target[0]]['quota_pool']}
    for scope, key in resources.items():
        row = conn.execute('''SELECT until_at,reason,updated_at FROM pipeline_route_holds
            WHERE scope=? AND resource_key=? AND until_at>?''', (scope,key,time.time())).fetchone()
        if row is None or row[1] not in ('quota','busy','provider'):
            continue
        evidence = dict(zip(('provider','model','reasoning_effort'),target),
            status='AVAILABILITY_WAIT_UNTESTED', request_id=request.request_id, plan_digest=request.plan.digest,
            scope=scope, resource_key=key, until_at=row[0], failure_category=row[1], updated_at=row[2],
            native_probe_executed=False)
        conn.execute('INSERT INTO pipeline_task_catalog_holds VALUES(?,?,?)',
                     (request.request_id,encoded(list(target)).decode(),encoded(evidence).decode()))
        return True
    return False


@dataclass(frozen=True)
class _ProbeChange:
    previous_policy_digest: str
    policy: object
    changed_targets: tuple
    control_target: tuple
    digest: str


def probe_authority(request, target):
    """Use the existing slot protocol with a bounded one-target probe policy."""
    plan = request.plan
    target = tuple(target)
    if target not in set(plan.required_targets) | {plan.control_target}:
        raise ValueError('Task probe target is outside the reviewed request')
    policy = plan.policy.as_dict()
    entry = dict(zip(('provider','model','reasoning_effort'), target))
    tiers = {str(tier): [dict(entry)] for tier in range(1, 11)}
    # This is a captured one-target planning intent, using the existing scoped
    # catalog contract. The domain-separated digest binds its protected plan;
    # the generation string itself confers no publication authority.
    intent = dict(purpose='task_catalog_native_acceptance', plan_digest=plan.digest, target=list(target))
    policy.update(tiers=tiers, catalog=dict(schema='cochem-routing-catalog/3',
                  generation='planning428-'+digest(intent)[:32], tiers=tiers),
                  model_limits={':'.join(target):plan.model_limits.get(':'.join(target))})
    change = _ProbeChange(plan.previous_policy_digest, load_routing_policy(policy),
                          (target,), target, plan.digest)
    return CatalogAuthority(request.request_id, request.pointer_sha256, request.proposal_sha256, change)


def probe_node(request, target, reservation):
    authority = probe_authority(request, target)
    details = dict(zip(('provider','model','reasoning_effort'), target),
                   worker=reservation['worker_slot'], route_positions=[dict(tier=1,choice=1)])
    node = make_probe(authority.change.policy, details, reservation['reservation_id'])
    node['fencing_token'] = node['route']['fencing_token'] = reservation['fencing_token']
    node['route']['reservation_id'] = reservation['reservation_id']
    return node, details


def record_result(conn, request, target, reservation, *, output=None, receipt=None,
                  binary_sha256, cleanup_verified, availability=None):
    """Trusted native adapter only; never accept a model-supplied acceptance flag."""
    catalog_journal._transaction(conn)
    node, details = probe_node(request, target, reservation)
    binding = request.plan.binary_bindings[target[0]]
    if binary_sha256 != binding['sha256']:
        raise ValueError('Task probe executable differs from the reviewed binary')
    row = conn.execute('''SELECT plan_digest,pointer_sha256,proposal_sha256,target_json
        FROM pipeline_catalog_probes WHERE reservation_id=?''', (reservation['reservation_id'],)).fetchone()
    if row is None or tuple(row) != (request.plan.digest, request.pointer_sha256,
                                    request.proposal_sha256, json.dumps(list(target),separators=(',',':'))):
        raise ValueError('Task probe reservation differs from request')
    if cleanup_verified is not True:
        catalog_slots.finish(conn, reservation, cleanup_verified=False, accepted=False)
        return dict(status='CLEANUP_UNVERIFIED', activation_ready=False)
    if availability is not None:
        if not isinstance(availability, ProviderFailure) or availability.category not in ('quota','busy','provider'):
            raise ValueError('Only typed temporary provider availability can defer a target')
        evidence = dict(status='AVAILABILITY_WAIT', failure_category=availability.category)
        from .routing_store import set_hold
        policy = request.plan.policy.as_dict()
        scope = availability.hold_scope
        if scope in ('pool','model'):
            resource = policy['provider_limits'][target[0]]['quota_pool'] if scope=='pool' else ':'.join(target)
            seconds = max(policy.get('failure_cooldowns',{}).get(availability.category,30),
                          availability.retry_after_seconds or 0)
            set_hold(conn,scope,resource,seconds,availability.category)
    else:
        validate_result(details, output, receipt)
        for key in ('job_id','workflow_id','attempt_id','fencing_token'):
            if receipt.get(key) != node[key]:
                raise ValueError('Task probe native receipt identity differs')
        effort = receipt['inference_policy'].get('reasoning_effort', {})
        if (receipt.get('route_reservation_id') != reservation['reservation_id']
                or receipt.get('execution_kind') != 'native_cli'
                or receipt.get('process_identity_source') != 'owned_windows_process_handle'
                or receipt.get('output_sha256') != digest(output)
                or effort.get('requested_profile') != target[2] or effort.get('model') != target[1]
                or effort.get('executable_sha256') != binary_sha256 or effort.get('version') != binding['version']):
            raise ValueError('Task probe lacks exact native binary/effort/fence evidence')
        evidence = dict(status='NATIVE_SELECTOR_ACCEPTED', receipt_sha256=digest(receipt),
                        output_sha256=digest(output))
    catalog_slots.finish(conn, reservation, cleanup_verified=True,
                         accepted=evidence['status']=='NATIVE_SELECTOR_ACCEPTED')
    state = conn.execute('SELECT result_json FROM pipeline_catalog_probes WHERE reservation_id=?',
                         (reservation['reservation_id'],)).fetchone()
    if evidence['status']=='NATIVE_SELECTOR_ACCEPTED' and json.loads(state[0])['status']!='NATIVE_SELECTOR_ACCEPTED':
        raise ValueError('Task probe acceptance lease expired before completion')
    evidence.update(provider=target[0],model=target[1],reasoning_effort=target[2],
        execution_binding=request.execution_bindings[target[0]],
        binary_sha256=binary_sha256,cleanup_verified=True,request_id=request.request_id,
        plan_digest=request.plan.digest,reservation_id=reservation['reservation_id'],
        fencing_token=reservation['fencing_token'])
    conn.execute('INSERT INTO pipeline_task_probe_evidence VALUES(?,?,?,?)',
        (reservation['reservation_id'],request.request_id,request.plan.digest,encoded(evidence).decode()))
    return evidence


def publish(conn, request):
    """Publish and consume exact durable native evidence in the caller transaction."""
    catalog_journal._transaction(conn)
    rows = conn.execute('''SELECT p.plan_digest,p.pointer_sha256,p.proposal_sha256,p.cleanup_at,
        p.result_json,e.evidence_json FROM pipeline_catalog_probes p
        LEFT JOIN pipeline_task_probe_evidence e USING(reservation_id) WHERE p.request_id=?''',
        (request.request_id,)).fetchall()
    if not rows or any(tuple(row[:3]) != (request.plan.digest,request.pointer_sha256,request.proposal_sha256)
                       or row[3] is None or row[4] is None or row[5] is None for row in rows):
        raise ValueError('Task catalog has missing, uncleaned or unbound durable probe evidence')
    receipts = [json.loads(row[5]) for row in rows]
    for row, receipt in zip(rows, receipts):
        native = json.loads(row[4])
        for key in ('provider','model','reasoning_effort','request_id','plan_digest','reservation_id','fencing_token'):
            if native.get(key) != receipt.get(key):
                raise ValueError('Task catalog evidence differs from its capacity fence')
        if receipt['status']=='NATIVE_SELECTOR_ACCEPTED' and native['status']!='NATIVE_SELECTOR_ACCEPTED':
            raise ValueError('Task catalog accepted evidence contradicts its probe outcome')
        if receipt.get('execution_binding') != request.execution_bindings[receipt['provider']]:
            raise ValueError('Task catalog evidence differs from its provider/agent contract')
    holds = [json.loads(row[0]) for row in conn.execute(
        'SELECT evidence_json FROM pipeline_task_catalog_holds WHERE request_id=? ORDER BY target_json',
        (request.request_id,))]
    already = conn.execute('SELECT 1 FROM pipeline_task_catalog_generations WHERE request_id=?',
                           (request.request_id,)).fetchone() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='pipeline_task_catalog_generations'").fetchone() else None
    if not already:
        for hold in holds:
            actual = conn.execute('''SELECT until_at,reason,updated_at FROM pipeline_route_holds
                WHERE scope=? AND resource_key=? AND until_at>?''',
                (hold['scope'],hold['resource_key'],time.time())).fetchone()
            if actual is None or tuple(actual) != (hold['until_at'],hold['failure_category'],hold['updated_at']):
                raise ValueError('Task catalog untested availability snapshot is no longer current')
    result = catalog_journal.publish_task_catalog(conn, request.plan, receipts,
        request_id=request.request_id,pointer_sha256=request.pointer_sha256,proposal_sha256=request.proposal_sha256,
        unprobed_holds=holds,allow_partial_publication=request.allow_partial_publication)
    if not any(row['status']=='AVAILABLE' for row in coverage(result['catalog'],conn=conn)):
        raise ValueError('Task catalog has no usable route coverage; publication held')
    conn.execute('UPDATE pipeline_catalog_probes SET consumed_at=coalesce(consumed_at,?) WHERE request_id=?',
                 (time.time(),request.request_id))
    return result


def enabled_candidate(conn, request, configuration, *, catalog_path, catalog_bytes,
                      flash_context_limit=None):
    """Pure candidate config after publication; caller writes a new protected file."""
    if not conn.in_transaction:
        raise ValueError('Task configuration requires a coherent publication snapshot')
    catalog = catalog_journal.active_task_catalog(conn)
    if (catalog is None or catalog.get('request_id') != request.request_id
            or catalog.get('plan_digest') != request.plan.digest
            or catalog.get('pointer_sha256') != request.pointer_sha256
            or catalog.get('proposal_sha256') != request.proposal_sha256
            or _strict_json(catalog_bytes.decode()) != catalog):
        raise ValueError('Task planning cannot enable before exact catalog publication')
    from .planning_runtime import PlanningConfig
    spec = dict(catalog_file=str(catalog_path),catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(),
                flash_context_limit=flash_context_limit)
    PlanningConfig.from_dict(spec)
    candidate = deepcopy(configuration)
    if load_routing_policy(candidate['routing']).digest != request.plan.policy.digest:
        raise ValueError('Task planning configuration routing differs from published policy')
    if (candidate.get('max_execution_slots') != 4 or
            execution_bindings(candidate.get('providers'),candidate.get('workers')) != request.execution_bindings):
        raise ValueError('Task planning configuration differs from accepted provider/profile bindings')
    candidate.update(catalog_activation=True,task_planning=spec)
    return candidate


def coverage(catalog, *, conn=None):
    """Report accepted choices and live holds explicitly; never lower a floor.

    Without a board snapshot this reports native capability only. With the
    publication transaction it also excludes current model/provider/pool holds.
    Research, input size, and human SRS approval remain task-specific gates.
    """
    rows = []
    models = catalog['models']
    from .task_routing import select_reviewers
    blockers = {}
    if conn is not None:
        if not conn.in_transaction:
            raise ValueError('Live route coverage requires a coherent board snapshot')
        policy = catalog_journal.active_policy(conn).as_dict()
        for key, model in models.items():
            target=(model['provider'],model['model'],model['effort'])
            scopes={'model':':'.join(target) if all(target) else '', 'provider':target[0],
                    'pool':policy['provider_limits'][target[0]]['quota_pool']}
            for scope, resource in scopes.items():
                held=conn.execute('''SELECT reason FROM pipeline_route_holds
                    WHERE scope=? AND resource_key=? AND until_at>?''',(scope,resource,time.time())).fetchone()
                if held is not None:
                    blockers[key]=dict(scope=scope,reason=held[0]);break
    available_ids={key for key,model in models.items()
                   if model.get('native_acceptance')=='ACCEPTED' and key not in blockers}
    for tag, spec in catalog['task_types'].items():
        for tier, row in spec['tiers'].items():
            choices = [key for key in row['choices'] if key not in blockers]
            reviewers={key:select_reviewers(catalog,[tag],int(tier),key,available_ids=available_ids)
                       for key in choices}
            review_ok = bool(choices) and all(reviewers.values())
            rows.append(dict(task_type=tag,complexity=int(tier),floor=row['floor'],
                accepted_choices=list(row['choices']),eligible_choices=list(choices),
                availability_holds={key:blockers[key] for key in row['choices'] if key in blockers},
                ranked_option_count=len(row.get('ranked_options',[])),
                live_availability_checked=conn is not None,
                reviewer_candidates=reviewers,
                executable=bool(choices),different_family_review_available=bool(review_ok),
                status='AVAILABLE' if choices and (int(tier)<4 or review_ok) else 'HELD_COVERAGE'))
    return rows


def run_acceptance(runtime, request):
    """SYSTEM owner wrapper only; sequential probes, no interactive login/retry.

    The caller retains protected_request custody and supplies an already guarded
    runtime/admission/RAM context. No controller/task/service lifecycle occurs.
    """
    from . import windows
    from .native_effort import verified_executable_sha256
    from .worker import NativeRunner, WorkerCleanupError
    from .runtime import clear_ram_workspace
    windows.require_system()
    if execution_bindings(runtime.config.providers,runtime.config.workers) != request.execution_bindings:
        raise ValueError('Protected provider/agent configuration differs from acceptance request')
    with runtime.store._write() as conn:
        initialize(conn)
    targets = sorted(set(request.plan.required_targets) | {request.plan.control_target})
    for index, target in enumerate(targets):
        authority = probe_authority(request, target)
        with runtime.store._connection() as conn:
            prior = conn.execute('''SELECT p.plan_digest,p.pointer_sha256,p.proposal_sha256,
                p.cleanup_at,p.result_json,e.evidence_json FROM pipeline_catalog_probes p
                LEFT JOIN pipeline_task_probe_evidence e USING(reservation_id)
                WHERE p.request_id=? AND p.target_json=?''',
                (request.request_id, json.dumps(list(target),separators=(',',':')))).fetchone()
        if prior:
            # Continuation reuses only exact immutable final evidence. A failed
            # or unknown earlier attempt must stop before any further dispatch.
            if (tuple(prior[:3]) != (request.plan.digest,request.pointer_sha256,request.proposal_sha256)
                    or any(prior[index] is None for index in (3,4,5))):
                raise ValueError('Earlier task catalog probe requires review; no automatic retry')
            continue
        with runtime.store._write() as conn:
            held = conn.execute('SELECT 1 FROM pipeline_task_catalog_holds WHERE request_id=? AND target_json=?',
                (request.request_id,encoded(list(target)).decode())).fetchone()
            if held or defer_held_target(conn,request,target):
                continue
        slot = sorted(runtime.config.workers)[index % len(runtime.config.workers)]
        binding = request.plan.binary_bindings[target[0]]
        executable = runtime.config.providers[target[0]]['executable']
        if executable != binding['executable'] or verified_executable_sha256(executable) != binding['sha256']:
            raise ValueError('Installed task catalog executable differs from reviewed binding')
        token = runtime.admission.reserve_catalog(authority,target,worker_slot=slot,
            containment_id=runtime.catalog_containment_id,boot_id=runtime.boot_id)
        if token is None:
            return dict(status='WAITING_ADMISSION',request_id=request.request_id,
                        target=dict(zip(('provider','model','effort'),target)),activation_ready=False)
        node, details = probe_node(request,target,token)
        def heartbeat():
            if runtime.stop_event.is_set() or getattr(runtime,'last_admission_action',None)=='terminate_active':
                return False
            with runtime.store._connection() as conn:
                row=conn.execute('SELECT lease_expires_at,cleanup_at FROM pipeline_catalog_probes WHERE reservation_id=?',
                                 (token['reservation_id'],)).fetchone()
            return row is not None and row[0]>time.time() and row[1] is None
        output=receipt=availability=None
        cleaned=True
        error=None
        descriptor=None
        try:
            descriptor = runtime.ramdisk.workspace(slot)
            runner = NativeRunner(replace(runtime.config,routing=authority.change.policy,timeout_seconds=60))
            descriptor.validate(identity=runtime.config.workers[slot]['name'],cwd=descriptor.root)
            output,receipt=runner.run(node,slot,'',heartbeat,workspace=descriptor.root,ramdisk_workspace=descriptor)
            if receipt.get('worker_account') != runtime.config.workers[slot]['name']:
                raise ValueError('Task probe native worker account differs from protected profile')
        except WorkerCleanupError as exc:
            cleaned=False;error=exc
        except ProviderFailure as exc:
            if exc.category in ('quota','busy','provider'):availability=exc
            else:error=exc
        except Exception as exc:
            # Unknown failure cannot attest process closure.
            cleaned=False;error=exc
        if cleaned and descriptor is not None:
            try:clear_ram_workspace(descriptor)
            except Exception as exc:cleaned=False;error=exc
        try:
            if error is not None:
                with runtime.store._write() as conn:
                    catalog_slots.finish(conn,token,cleanup_verified=cleaned,accepted=False)
                raise error
            if verified_executable_sha256(executable) != binding['sha256']:
                raise ValueError('Task catalog executable changed during native acceptance')
            with runtime.store._write() as conn:
                record_result(conn,request,target,token,output=output,receipt=receipt,
                              binary_sha256=binding['sha256'],cleanup_verified=cleaned,availability=availability)
        except Exception:
            # Validation failure after physical closure is still a failed probe,
            # but does not leak its seat. Unknown cleanup stays occupied.
            with runtime.store._write() as conn:
                row=conn.execute('SELECT cleanup_at FROM pipeline_catalog_probes WHERE reservation_id=?',
                                 (token['reservation_id'],)).fetchone()
                if row is not None and row[0] is None:
                    catalog_slots.finish(conn,token,cleanup_verified=cleaned,accepted=False)
            raise
        finally:
            runtime.admission.request_maintenance()
    if runtime.stop_event.is_set() or getattr(runtime,'last_admission_action',None)=='terminate_active':
        raise RuntimeError('Task catalog acceptance was revoked before publication')
    with runtime.store._write() as conn:
        result=publish(conn,request)
        route_coverage = coverage(result['catalog'],conn=conn)
    return dict(result, coverage=route_coverage, catalog_published=True,
                all_routes_usable=all(row['status']=='AVAILABLE' for row in route_coverage),
                coverage_holds=sum(row['status']!='AVAILABLE' for row in route_coverage),
                native_acceptance_scope='recorded_exact_targets_only')
