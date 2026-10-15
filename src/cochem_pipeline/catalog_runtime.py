"""Protected-pointer hot catalog coordinator. No HTTP activation surface."""
from __future__ import annotations

from dataclasses import replace
import json
import time
import hashlib
import os
import uuid

from . import catalog_journal, catalog_slots
from .catalog_authority import protected_catalog_request
from .r6_native_acceptance import make_probe, validate_result


class CatalogController:
    def __init__(self, runtime, reader=protected_catalog_request):
        self.runtime=runtime;self.reader=reader
        self.custody=None;self.authority=None;self.pending=[];self.future=None
        self.reservation=None;self.last_poll=0.;self.status={'status':'IDLE'}
        self.terminal=None
        # Scheduled-task Wardens do not have the optional supervisor launch
        # nonce. Catalog fencing therefore owns a separate per-controller
        # identity; NativeRunner independently owns the actual worker Job.
        self.containment_id=uuid.uuid4().hex

    def _close(self):
        if self.custody is not None:
            self.custody.__exit__(None,None,None);self.custody=None

    def close(self):
        # Runtime waits for its shared pool before releasing retained authority.
        if self.future is not None and not self.future.done():
            raise RuntimeError('Catalog native execution is still active')
        if self.future is not None:
            try:accepted,cleaned=self.future.result()
            except BaseException:accepted,cleaned=False,False
            with self.runtime.store._write() as conn:
                catalog_slots.finish(conn,self.reservation,cleanup_verified=cleaned,accepted=accepted)
            self.future=None
        self._close()

    def _hold(self, exc):
        self.terminal=None if self.authority is None else (self.authority.request_id,self.authority.pointer_sha256)
        self.status={'status':'HELD','error_type':type(exc).__name__,'automatic_retry':False}
        self._close()
        self.authority=None

    def step(self, available, capacity):
        """Called by the scheduler under its lock; never waits for a provider."""
        rt=self.runtime
        try:
            if self.future is not None:
                if not self.future.done():return
                try:accepted,cleaned=self.future.result()
                except BaseException:
                    # Unknown executor failure cannot establish native cleanup.
                    accepted,cleaned=False,False
                with rt.store._write() as conn:
                    catalog_slots.finish(conn,self.reservation,cleanup_verified=cleaned,accepted=accepted)
                rt.admission.request_maintenance()
                self.future=None
                if not accepted or not cleaned:raise RuntimeError('Catalog probe did not pass')
                self.pending.pop(0)
            if self.authority is None:
                if time.monotonic()-self.last_poll<30:return
                self.last_poll=time.monotonic()
                with rt.store._connection() as conn:
                    policy=catalog_journal.active_policy(conn)
                def resolve(digest):
                    from .routing import load_routing_policy
                    with rt.store._connection() as conn:
                        row=conn.execute('SELECT policy_json FROM pipeline_catalog_generations WHERE policy_digest=?',(digest,)).fetchone()
                    if row is None:raise ValueError('Unknown preceding catalog generation')
                    return load_routing_policy(json.loads(row[0]))
                self.custody=self.reader(policy,resolver=resolve)
                try:self.authority=self.custody.__enter__()
                except FileNotFoundError:
                    self.custody=None;return
                identity=(self.authority.request_id,self.authority.pointer_sha256)
                with rt.store._connection() as conn:
                    published=conn.execute('SELECT pointer_sha256,proposal_sha256,policy_digest FROM pipeline_catalog_generations WHERE request_id=?',
                        (self.authority.request_id,)).fetchone()
                if published is not None:
                    if tuple(published[:2])!=(self.authority.pointer_sha256,self.authority.proposal_sha256):
                        raise ValueError('Published catalog request was replaced')
                    self.status={'status':'ALREADY_PUBLISHED','request_id':self.authority.request_id,'policy_digest':published[2]}
                if published is not None or identity==self.terminal:
                    self._close();self.authority=None;return
                self.pending=sorted(set(self.authority.change.changed_targets)|{self.authority.change.control_target})
                with rt.store._connection() as conn:
                    prior=conn.execute('''SELECT plan_digest,pointer_sha256,proposal_sha256,target_json,
                        cleanup_at,result_json FROM pipeline_catalog_probes WHERE request_id=?''',
                        (self.authority.request_id,)).fetchall()
                for row in prior:
                    if (tuple(row[:3])!=(self.authority.change.digest,self.authority.pointer_sha256,self.authority.proposal_sha256)
                            or row[4] is None or row[5] is None
                            or json.loads(row[5]).get('status')!='NATIVE_SELECTOR_ACCEPTED'):
                        raise ValueError('Earlier probe needs review; no automatic retry')
                    self.pending.remove(tuple(json.loads(row[3])))
            if not self.pending:
                with rt.store._write() as conn:result=catalog_slots.publish(conn,self.authority)
                self.status={**result,'request_id':self.authority.request_id}
                self._close()
                self.authority=None
                return
            if capacity<=0 or not available or rt.ramdisk is None:return
            slot=available[0];target=self.pending[0]
            token=rt.admission.reserve_catalog(self.authority,target,worker_slot=slot,
                containment_id=self.containment_id,boot_id=rt.boot_id)
            if token is None:return
            self.reservation=token
            try:self.future=rt.pool.submit(self._execute,target,slot,token)
            except BaseException:
                with rt.store._write() as conn:catalog_slots.finish(conn,token,cleanup_verified=True,accepted=False)
                raise
            self.status={'status':'PROBING','request_id':self.authority.request_id}
        except Exception as exc:self._hold(exc)

    def _probe_lease_valid(self, reservation_id):
        """Heartbeat for an admitted catalog probe.

        A pause (capacity 0, action pause_admission) only blocks new work.
        Revoking an admitted probe on a pause turned one controller CPU sample
        into a permanent catalog hold; only shutdown, critical pressure
        (terminate_active), or a cleaned or expired reservation revokes it,
        exactly as ordinary jobs are revoked only on resource trips.
        """
        rt=self.runtime
        if rt.stop_event.is_set() or getattr(rt,'last_admission_action',None)=='terminate_active':return False
        with rt.store._connection() as conn:
            row=conn.execute('SELECT lease_expires_at,cleanup_at FROM pipeline_catalog_probes WHERE reservation_id=?',
                (reservation_id,)).fetchone()
        return row is not None and row[1] is None and row[0]>time.time()

    def _execute(self, target, slot, token):
        from .worker import NativeRunner, WorkerCleanupError
        from .runtime import clear_ram_workspace
        rt=self.runtime;policy=self.authority.change.policy
        # A retired control target is probed with the preceding immutable policy.
        if target==self.authority.change.control_target:
            with rt.store._connection() as conn:policy=catalog_journal.active_policy(conn)
        positions=[{'tier':int(tier),'choice':i+1} for tier,rows in policy.as_dict()['tiers'].items()
            for i,row in enumerate(rows) if tuple(row[k] for k in ('provider','model','reasoning_effort'))==target]
        details=dict(zip(('provider','model','reasoning_effort'),target),worker=slot,route_positions=positions)
        node=make_probe(policy,details,token['reservation_id'])
        node['fencing_token']=node['route']['fencing_token']=token['fencing_token']
        node['route']['reservation_id']=token['reservation_id']
        def heartbeat():
            return self._probe_lease_valid(token['reservation_id'])
        descriptor=rt.ramdisk.workspace(slot)
        runner=NativeRunner(replace(rt.config,routing=policy,timeout_seconds=60))
        cleaned=True;accepted=False
        try:
            descriptor.validate(identity=rt.config.workers[slot]['name'],cwd=descriptor.root)
            output,receipt=runner.run(node,slot,'',heartbeat,workspace=descriptor.root,ramdisk_workspace=descriptor)
            observation=validate_result(details,output,receipt);accepted=True
        except WorkerCleanupError:cleaned=False
        except Exception:accepted=False
        if cleaned:
            try:clear_ram_workspace(descriptor)
            except Exception:cleaned=False
        if accepted and cleaned:
            # NativeRunner preserves full private output/receipt logs. This
            # durable record links their hashes to the protected proposal and
            # actual capacity fence before publication can consume the probe.
            evidence=dict(schema='cochem-catalog-native-probe/1',request_id=self.authority.request_id,
                plan_digest=self.authority.change.digest,pointer_sha256=self.authority.pointer_sha256,
                proposal_sha256=self.authority.proposal_sha256,reservation=token,target=details,
                receipt_sha256=hashlib.sha256(json.dumps(receipt,sort_keys=True,allow_nan=False).encode()).hexdigest(),
                output_sha256=hashlib.sha256(json.dumps(output,sort_keys=True,allow_nan=False).encode()).hexdigest(),observation=observation,
                cleanup_verified=True)
            try:
                path=rt.config.private_root/'attempts'/node['attempt_id']/'catalog-evidence.json'
                with path.open('x',encoding='utf-8') as out:
                    json.dump(evidence,out,indent=2,allow_nan=False);out.flush();os.fsync(out.fileno())
            except Exception:accepted=False
        return accepted,cleaned
