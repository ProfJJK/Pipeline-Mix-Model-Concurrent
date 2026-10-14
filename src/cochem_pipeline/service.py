"""Narrow authenticated loopback API. Workers have no claim or completion endpoint."""
from __future__ import annotations
import hmac
import hashlib
from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit


# Heavy read projections are built and encoded one at a time per lock.
# Concurrent builds multiplied transient allocator high-water in the Warden.
# Operator views (/operator, /operator/workflow/*, /operator/job/*) share one
# lock; workflow status reads (/workflow/*, /coding/workflow/*) have their own
# lock with the same bounded wait, so a status poll never queues behind an
# operator build. /health, /knowledge/* and every POST stay outside both locks.
PROJECTION_WAIT_SECONDS = 20.0
OPERATOR_PROJECTION_PREFIXES = ('/operator/workflow/','/operator/job/')
WORKFLOW_PROJECTION_PREFIXES = ('/workflow/','/coding/workflow/','/tasks/status/')
PROJECTION_PREFIXES = OPERATOR_PROJECTION_PREFIXES+WORKFLOW_PROJECTION_PREFIXES


def heavy_projection(path: str) -> bool:
    return path=='/operator' or path.startswith(PROJECTION_PREFIXES)


def operator_projection(path: str) -> bool:
    return path=='/operator' or path.startswith(OPERATOR_PROJECTION_PREFIXES)


def encode_json(data) -> bytes:
    # Same JSON value as before, without a 2-byte-per-character intermediate
    # str for non-ASCII text and without separator whitespace.
    return json.dumps(data,ensure_ascii=True,separators=(',',':')).encode('ascii')


def redact(value):
    if isinstance(value,dict):
        public = {key:(deepcopy(item) if key in ('payload','output','artifacts') else redact(item))
                for key,item in value.items()
                if key not in ('fencing_token','attempt_id','lease_owner','owner',
                               'reservation_id','route_reservation_id')}
        # Keep a verifiable join between an assignment and its native receipt
        # without publishing the private database reservation identifier.
        for source, target in (('reservation_id','reservation_sha256'),
                               ('route_reservation_id','route_reservation_sha256')):
            if isinstance(value.get(source),str) and value[source]:
                public[target] = hashlib.sha256(value[source].encode('utf-8')).hexdigest()
        if isinstance(value.get('receipt'),dict):
            # Commit to the actual immutable receipt before private lease and
            # reservation fields are redacted from the authenticated view.
            public['receipt_sha256']=hashlib.sha256(json.dumps(value['receipt'],sort_keys=True,
                separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        return public
    if isinstance(value,list):
        return [redact(item) for item in value]
    return value


def public_workflow(workflow: dict) -> dict:
    # Fencing tokens and leases are control-plane authority, never model/tool output.
    return redact(workflow)


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self,runtime,token: str):
        if len(token)<32:
            raise ValueError('Controller token must contain at least 32 random characters')
        self.runtime,self.token = runtime,token
        from .operator_views import OperatorViewHistory
        self.operator_history=OperatorViewHistory()
        self.projection_lock = threading.Lock()  # operator views
        self.workflow_projection_lock = threading.Lock()  # workflow status reads
        self.projection_wait_seconds = PROJECTION_WAIT_SECONDS
        self._requests = threading.BoundedSemaphore(16)
        super().__init__(('127.0.0.1',runtime.config.port),Handler)

    def get_request(self):
        request,address = super().get_request()
        request.settimeout(5)
        return request,address

    def process_request(self,request,client_address):
        if not self._requests.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request,client_address)
        except BaseException:
            self._requests.release()
            raise

    def process_request_thread(self,request,client_address):
        try:
            super().process_request_thread(request,client_address)
        finally:
            self._requests.release()


class Handler(BaseHTTPRequestHandler):
    server: ControlServer
    protocol_version = 'HTTP/1.1'
    disable_nagle_algorithm = True
    def log_message(self,*args):
        # Default HTTP logs may include user-supplied paths; structured service logs suffice.
        return None

    def reply(self,code,data):
        self.send_payload(code,encode_json(data))

    def send_payload(self,code,payload):
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(payload)))
        if self.close_connection:
            self.send_header('Connection','close')
        self.end_headers()
        self.wfile.write(payload)
        objectives=getattr(self.server.runtime,'objectives',None)
        started=getattr(self,'_observed_started',None)
        if started is not None and objectives is not None and hasattr(objectives,'record_async'):
            objectives.record_async('interactive',self._observed_operation,time.monotonic()-started,
                                    code<400,uuid.uuid4().hex)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def _discard_rejected_body(self):
        # Closing an unread POST can reset TCP on Windows before the caller
        # receives its 401. Send the rejection first, then discard only a bounded
        # declared body. Never parse it or reuse this unauthorized connection.
        try:
            remaining=int(self.headers.get('Content-Length','0'))
        except ValueError:
            return
        if not 1<=remaining<=4*1024*1024:
            return
        deadline=time.monotonic()+1.0
        previous_timeout=self.connection.gettimeout()
        try:
            while remaining:
                timeout=deadline-time.monotonic()
                if timeout<=0:
                    return
                self.connection.settimeout(timeout)
                chunk=self.rfile.read1(min(65536,remaining))
                if not chunk:
                    return
                remaining-=len(chunk)
        except OSError:
            # A peer may stop sending or close after reading its 401. The
            # response is already sent; this connection is always discarded.
            pass
        finally:
            self.connection.settimeout(previous_timeout)

    def _projection(self,runtime,path):
        # Called only while the path's projection lock is held.
        if path.startswith('/tasks/status/'):
            return redact(runtime.task_status(path[len('/tasks/status/'):]))
        if path.startswith('/coding/workflow/'):
            return public_workflow(runtime.coding_workflow(path[len('/coding/workflow/'):]))
        if path.startswith('/workflow/'):
            return public_workflow(runtime.store.workflow(path[len('/workflow/'):]))
        from .operator_views import operator_snapshot
        workflow_id=path[len('/operator/workflow/'):] if path.startswith('/operator/workflow/') else None
        job_id=path[len('/operator/job/'):] if path.startswith('/operator/job/') else None
        query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,max_num_fields=2)
        if set(query)-{'after_event_id','view'} or any(len(values)!=1 for values in query.values()):
            raise ValueError('Operator view accepts one after_event_id cursor and one view')
        cursor=int(query['after_event_id'][0]) if 'after_event_id' in query else None
        return redact(operator_snapshot(runtime,workflow_id,job_id=job_id,after_event_id=cursor,
                                        history=self.server.operator_history,view=query.get('view',['full'])[0]))

    def dispatch(self):
        started=time.monotonic()
        self._observed_started=None
        supplied=self.headers.get('Authorization','')
        if not hmac.compare_digest(supplied.encode('utf-8'),('Bearer '+self.server.token).encode('utf-8')):
            self.close_connection=True
            self.reply(401,{'error':'Unauthorized'})
            self._discard_rejected_body()
            return
        runtime=self.server.runtime
        path=urlsplit(self.path).path
        # Record only a bounded route name, never a query, workflow ID, bearer
        # token, request body or returned artifact. The bounded async writer
        # exposes dropped samples and keeps SQLite writes off the HTTP path.
        self._observed_started=started
        self._observed_operation=(path if path in {'/health','/operator','/knowledge/status',
            '/knowledge/search','/knowledge/read','/knowledge/refresh','/coding/projects',
            '/submit','/preflight','/cancel','/routing/resume','/coding/submit','/coding/cancel','/coding/resume','/tasks/submit'}
            else '/operator/workflow' if path.startswith('/operator/workflow/')
            else '/operator/job' if path.startswith('/operator/job/')
            else '/coding/workflow' if path.startswith('/coding/workflow/')
            else '/workflow' if path.startswith('/workflow/')
            else '/tasks/status' if path.startswith('/tasks/status/') else '/unknown')
        try:
            if self.command=='GET' and path=='/health':
                self.reply(200,redact(runtime.status()))
            elif self.command=='GET' and heavy_projection(path):
                # Bounded wait, then build and encode under the path's lock. The lock
                # is released before the socket write so a slow reader cannot stall
                # other callers; only the encoded bytes outlive the projection.
                lock=(self.server.projection_lock if operator_projection(path)
                      else self.server.workflow_projection_lock)
                if not lock.acquire(timeout=self.server.projection_wait_seconds):
                    self.reply(503,{'error':'Operator projection busy; retry'})
                    return
                try:
                    payload=encode_json(self._projection(runtime,path))
                finally:
                    lock.release()
                self.send_payload(200,payload)
            elif self.command=='GET' and path=='/knowledge/status':
                self.reply(200,runtime.knowledge_authority.status() if hasattr(runtime,'knowledge_authority')
                           else runtime.knowledge.status())
            elif self.command=='GET' and path=='/coding/projects':
                self.reply(200,{'projects':sorted(runtime.config.coding_projects)})
            elif self.command=='POST' and path in ('/submit','/preflight','/cancel','/routing/resume',
                                                  '/coding/submit','/coding/cancel','/coding/resume',
                                                  '/knowledge/search','/knowledge/read','/knowledge/refresh','/tasks/submit'):
                size=int(self.headers.get('Content-Length','0'))
                if not 1<=size<=4*1024*1024:
                    raise ValueError('Request body must be 1..4194304 bytes')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):
                    raise ValueError('Request must be a JSON object')
                if path=='/tasks/submit':
                    if set(data)-{'objective','task_id'}:
                        raise ValueError('Task intake accepts only objective and optional task_id; planning assigns all gates and routes')
                    self.reply(202,redact(runtime.submit_task(data['objective'],data.get('task_id'))))
                elif path=='/preflight':
                    if set(data)-{'workflow_id'}:
                        raise ValueError('Preflight accepts only an optional workflow_id; Chapter 06 assigns its model')
                    self.reply(202,public_workflow(runtime.store.submit_preflight(data.get('workflow_id'))))
                elif path=='/knowledge/search':
                    self.reply(200,{'results':runtime.knowledge.search(data['query'],data.get('limit',5))})
                elif path=='/knowledge/read':
                    self.reply(200,runtime.knowledge.read(data['doc_path']))
                elif path=='/knowledge/refresh':
                    if set(data)-{'full'} or type(data.get('full',False)) is not bool:
                        raise ValueError('Knowledge refresh accepts only a boolean full flag')
                    self.reply(200,runtime.knowledge.refresh(full=data.get('full',False)))
                elif path=='/coding/submit':
                    workflow=runtime.submit_coding(data['project_id'],data['objective'],
                        data.get('requirements',['REQ-001']),workflow_id=data.get('workflow_id'))
                    self.reply(202,public_workflow(workflow))
                elif path=='/coding/cancel':
                    self.reply(200,public_workflow(runtime.cancel_coding(data['workflow_id'])))
                elif path=='/coding/resume':
                    reason=data.get('reason')
                    if not isinstance(reason,str) or not reason.strip() or len(reason)>512 or '\x00' in reason:
                        raise ValueError('Coding resume requires an operator reason of at most 512 characters')
                    self.reply(200,public_workflow(runtime.resume_coding(data['workflow_id'],reason.strip())))
                elif path=='/submit':
                    count=data.get('chapter_count',6)
                    if type(count) is not int or not 1<=count<=len(runtime.config.workers):
                        raise ValueError('chapter_count must fit the provisioned distinct worker identity pool')
                    workflow=runtime.store.submit(data['objective'],data.get('requirements',['REQ-001']),
                                                  count,data.get('workflow_id'),max_attempts=data.get('max_attempts'),
                                                  max_dispatches=data.get('max_dispatches'))
                    self.reply(202,public_workflow(workflow))
                elif path=='/cancel':
                    runtime.cancel(data['workflow_id'])
                    self.reply(200,public_workflow(runtime.store.workflow(data['workflow_id'])))
                else:
                    reason=data.get('reason')
                    if not isinstance(reason,str) or not reason.strip() or len(reason)>512 or '\x00' in reason:
                        raise ValueError('Routing resume requires a nonempty operator reason of at most 512 characters')
                    job=runtime.store.resume_routing(data['job_id'],reason=reason.strip())
                    self.reply(200,public_workflow(runtime.store.workflow(job['workflow_id'])))
            else:
                self.reply(404,{'error':'Unknown operation; claim and completion are private to the Warden'})
        except (ValueError,KeyError,TypeError) as exc:
            self.reply(400,{'error':str(exc)})
        except Exception:
            self.reply(500,{'error':'Controller operation failed; inspect the protected Warden log'})


class ControlClient:
    def __init__(self,port:int,token_file:str|Path):
        if not 1024<=port<=65535:
            raise ValueError('Invalid controller port')
        self.port,self.token_file=port,Path(token_file)
        self._knowledge_lock=threading.Lock()
        self._knowledge_connection=None

    def call(self,operation:str,data:dict|None=None):
        if operation.startswith('/knowledge/'):
            # The read-only MCP repeatedly queries one authenticated controller.
            # Reusing its bounded connection removes TCP/thread setup per query;
            # every request still rereads the token and authenticates at the server.
            with self._knowledge_lock:
                if self._knowledge_connection is None:
                    self._knowledge_connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=30)
                try:
                    return self._call(operation,data,self._knowledge_connection)
                except BaseException:
                    self._knowledge_connection.close();self._knowledge_connection=None
                    raise
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=30)
        try:
            return self._call(operation,data,connection)
        finally:
            connection.close()

    def _call(self,operation,data,connection):
        token=self.token_file.read_text(encoding='utf-8').strip()
        body=json.dumps(data) if data is not None else None
        connection.request('POST' if data is not None else 'GET',operation,body,
                           {'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        response=connection.getresponse()
        value=json.loads(response.read())
        if response.status>=400:
            raise RuntimeError(value.get('error','Controller rejected request'))
        return value

    def close(self):
        with self._knowledge_lock:
            if self._knowledge_connection is not None:
                self._knowledge_connection.close();self._knowledge_connection=None
