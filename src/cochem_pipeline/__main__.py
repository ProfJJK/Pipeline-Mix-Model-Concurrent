"""Warden service and unprivileged client commands."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import stat
import sys
import threading
import time

from . import __version__
from .config import load_config
from .service import ControlClient

# A fixed name: under ``python -m cochem_pipeline`` __name__ is '__main__'.
LOG = logging.getLogger('cochem_pipeline.__main__')
# Reboot-safe start (r5, addendum A2): backoff between Docker preflight tries
# for --docker-wait-seconds N > 0. The clock references are module-level seams
# so tests drive the wait with a fake clock.
DOCKER_WAIT_FIRST_DELAY_SECONDS = 5
DOCKER_WAIT_MAX_DELAY_SECONDS = 30
_monotonic = time.monotonic
_sleep = time.sleep


def _utcnow():
    return datetime.now(timezone.utc)


def _is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _require_ordinary(chain) -> None:
    for entry in chain:
        if _is_reparse_point(entry):
            raise ValueError('--queue-launch-output-root must not be or pass through a reparse point: '+str(entry))


def queue_launch_output_child(root, private_root, *, now=None, pid=None) -> Path:
    """Prepare --queue-launch-output-root and name this start's fresh child.

    The root must lie strictly below private_root through ordinary directories:
    neither the root nor any directory between it and private_root may be a
    symbolic link, junction or other reparse point. A missing root (and any
    missing directory between it and private_root) is created. The child is
    only named, never created here: QueueLaunchObserver creates it with
    exist_ok=False and applies today's --queue-launch-output checks to it.
    """
    private = Path(private_root).resolve(strict=True)
    boundary = os.path.normcase(os.path.abspath(private_root))
    root = Path(os.path.abspath(root))
    outside = '--queue-launch-output-root must lie inside the configured private_root: '+str(root)
    chain, current = [], root
    while os.path.normcase(str(current)) != boundary:
        if current.parent == current:
            raise ValueError(outside)
        chain.append(current)
        current = current.parent
    if not chain:
        raise ValueError(outside)
    chain.reverse()  # from just below private_root down to the root itself
    _require_ordinary(chain)
    if private not in root.resolve().parents:
        raise ValueError(outside)
    root.mkdir(parents=True, exist_ok=True)
    _require_ordinary(chain)
    stamp = (_utcnow() if now is None else now).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    child = root/f'{stamp}-{os.getpid() if pid is None else pid}'
    if os.path.lexists(child):
        raise FileExistsError('Queue launch evidence directory already exists: '+str(child))
    return child


def _brief(error) -> str:
    return f'{type(error).__name__}: {error}'[:512]


def wait_for_docker(config, seconds) -> bool:
    """Wait up to ``seconds`` for the Docker preflight that Runtime runs at startup.

    Used only for --docker-wait-seconds N > 0, before Runtime(config) exists.
    The DockerRunner is built exactly as Runtime.__init__ builds it (same
    policy, state root and trusted operator; preflight never reads the boot
    identity, so none is queried). Failed tries are logged at WARNING and
    retried after 5 s, doubling to at most 30 s, never sleeping past the
    deadline; one last try runs at the deadline. This never raises for an
    unavailable engine: the caller then constructs Runtime once, exactly as
    without the option, so an engine that is still unavailable fails exactly
    as today. The probe runner holds no open handle: its constructor closes
    its SQLite connection and every Docker client process is waited for.
    Returns True when a preflight passed, otherwise False.
    """
    policy = getattr(config, 'docker', None)
    if policy is None or not policy.enabled:
        return False
    from .containers import DockerRunner
    started = _monotonic()
    try:
        runner = DockerRunner(policy, config.private_root/'containers', trusted_operator=config.operator_name)
    except Exception as error:
        LOG.warning('Docker wait skipped: the Docker runner could not be prepared (%s); '
                    'Runtime starts as without --docker-wait-seconds', _brief(error))
        return False
    deadline = started+seconds
    delay = DOCKER_WAIT_FIRST_DELAY_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            runner.preflight()
        except Exception as error:
            now = _monotonic()
            remaining = deadline-now
            pause = min(delay, remaining)
            action = (f'retrying in {pause:.0f} s' if remaining > 0
                      else 'giving up; Runtime starts as without --docker-wait-seconds')
            LOG.warning('Docker engine not ready: preflight try %d failed after %.0f of %d s (%s): %s',
                        attempt, now-started, seconds, action, _brief(error))
            if remaining <= 0:
                return False
            _sleep(pause)
            delay = min(delay*2, DOCKER_WAIT_MAX_DELAY_SECONDS)
        else:
            if attempt > 1:
                LOG.info('Docker engine ready after %d preflight tries in %.0f s', attempt, _monotonic()-started)
            return True


@contextmanager
def service_lock(path:Path):
    # Called only after SYSTEM and private-directory validation, before slot cleanup.
    import msvcrt
    handle=path.open('a+b')
    try:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0');handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        yield
    finally:
        handle.close()


def daemon(filename, queue_launch_output=None, queue_launch_output_root=None, docker_wait_seconds=0):
    if queue_launch_output is not None and queue_launch_output_root is not None:
        raise ValueError('--queue-launch-output and --queue-launch-output-root are mutually exclusive')
    if type(docker_wait_seconds) is not int or docker_wait_seconds < 0:
        raise ValueError('--docker-wait-seconds must be a whole number of seconds >= 0')
    from .windows import WorkerIdentity,require_system,validate_private_directory,validate_controller_token
    from .runtime import Runtime
    from .service import ControlServer
    config=load_config(filename)
    require_system()
    validate_private_directory(config.private_root)
    validate_controller_token(config.token_file,config.operator_name,
                              {k:WorkerIdentity(**v) for k,v in config.workers.items()})
    log = RotatingFileHandler(config.private_root/'warden.log',maxBytes=8*1024*1024,
                              backupCount=3,encoding='utf-8')
    log.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.getLogger().addHandler(log)
    from .crash import record_crash
    prior_thread_hook = threading.excepthook
    def crash_thread(args):
        try:
            record_crash(config.private_root, args.exc_value,
                         getattr(args.exc_value, 'category', 'code'))
        except Exception:
            logging.error('Private thread crash metadata could not be persisted')
        prior_thread_hook(args)
    threading.excepthook = crash_thread
    try:
        with service_lock(config.private_root/'warden.lock'):
            if queue_launch_output_root is not None:
                # A fresh child per start; the observer still creates it with
                # exist_ok=False exactly as for --queue-launch-output.
                queue_launch_output = queue_launch_output_child(queue_launch_output_root, config.private_root)
                LOG.info('Queue launch evidence for this start: %s', queue_launch_output)
            if docker_wait_seconds:
                # Only delays: Runtime is still constructed exactly once below,
                # and an engine that stayed unavailable fails there as today.
                wait_for_docker(config, docker_wait_seconds)
            runtime=Runtime(config)
            server=ControlServer(runtime,config.token_file.read_text(encoding='utf-8').strip())
            def stop(*_):
                runtime.stop_event.set()
            signal.signal(signal.SIGINT,stop)
            signal.signal(signal.SIGTERM,stop)
            thread=threading.Thread(target=server.serve_forever,daemon=True,name='warden-control')
            thread.start()
            runtime_started = False
            try:
                if queue_launch_output is not None:
                    from .queue_launch import QueueLaunchObserver
                    observation = QueueLaunchObserver(runtime, queue_launch_output)
                else:
                    observation = nullcontext()
                with observation:
                    runtime_started = True
                    runtime.run()
            finally:
                try:
                    if not runtime_started:
                        # An invalid observation destination must not leave the
                        # already constructed runtime's resources alive.
                        runtime.stop_event.set()
                        runtime.run()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=10)
    except Exception as exc:
        try:
            record_crash(config.private_root, exc, getattr(exc, 'category', 'code'))
        except Exception:
            logging.error('Private service crash metadata could not be persisted')
        raise
    finally:
        threading.excepthook = prior_thread_hook


def _wait_seconds(text):
    try:
        value=int(text)
    except ValueError:
        value=-1
    if value < 0:
        raise argparse.ArgumentTypeError(f'must be a whole number of seconds >= 0, got {text!r}')
    return value


def main():
    parser=argparse.ArgumentParser(description=f'CoChem {__version__} privileged planning and coding pipeline')
    parser.add_argument('--version',action='version',version=__version__)
    commands=parser.add_subparsers(dest='command',required=True)
    service=commands.add_parser('daemon')
    service.add_argument('--config',required=True)
    observation=service.add_mutually_exclusive_group()
    observation.add_argument('--queue-launch-output',help='New protected evidence directory for real Windows launch queue observations')
    observation.add_argument('--queue-launch-output-root',
                             help='Protected directory under private_root; every start observes into a fresh '
                                  '<UTC yyyymmddTHHMMSSZ>-<pid> child (reboot-safe)')
    service.add_argument('--docker-wait-seconds',type=_wait_seconds,default=0,
                         help='Wait up to N seconds for the Docker engine before starting the Runtime (default 0: no wait)')
    for name in ('doctor','provision-execution'):
        deployment=commands.add_parser(name)
        deployment.add_argument('--config',required=True)
    preview=commands.add_parser('upgrade-preview')
    preview.add_argument('--current-config',required=True)
    preview.add_argument('--proposed-config',required=True)
    for name in ('mcp','submit','status','cancel','health','projects','code','code-status','code-cancel','code-resume',
                 'knowledge-search','knowledge-read','knowledge-status','knowledge-refresh'):
        command=commands.add_parser(name)
        command.add_argument('--client-config',required=True)
        if name=='submit':
            command.add_argument('--objective',required=True)
            command.add_argument('--requirements',nargs='+',default=['REQ-001'])
            command.add_argument('--chapters',type=int,default=6)
        if name=='code':
            command.add_argument('--project',required=True)
            command.add_argument('--objective',required=True)
            command.add_argument('--requirements',nargs='+',default=['REQ-001'])
            command.add_argument('--workflow-id')
        if name in ('status','cancel','code-status','code-cancel','code-resume'):
            command.add_argument('workflow_id')
        if name=='code-resume':
            command.add_argument('--reason',required=True)
        if name=='knowledge-search':
            command.add_argument('query')
            command.add_argument('--limit',type=int,default=5)
        if name=='knowledge-read':
            command.add_argument('doc_path')
        if name=='knowledge-refresh':
            command.add_argument('--full',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,stream=sys.stderr)
    if args.command=='daemon':
        daemon(args.config,queue_launch_output=args.queue_launch_output,
               queue_launch_output_root=args.queue_launch_output_root,
               docker_wait_seconds=args.docker_wait_seconds)
        return
    if args.command in ('doctor','provision-execution'):
        from .deployment import execution_readiness
        report=execution_readiness(load_config(args.config),provision=args.command=='provision-execution')
        print(json.dumps(report,indent=2,ensure_ascii=False))
        raise SystemExit(0 if report['ready'] else 1)
    if args.command=='upgrade-preview':
        from .upgrade_preview import upgrade_preview
        print(json.dumps(upgrade_preview(args.current_config,args.proposed_config),indent=2,ensure_ascii=False))
        return
    config=json.loads(Path(args.client_config).read_text(encoding='utf-8-sig'))
    client=ControlClient(config.get('port',47824),config['token_file'])
    if args.command=='mcp':
        from .server import create_server
        create_server(client).run(transport='stdio')
        return
    if args.command=='knowledge-search':
        result=client.call('/knowledge/search',{'query':args.query,'limit':args.limit})
    elif args.command=='knowledge-read':
        result=client.call('/knowledge/read',{'doc_path':args.doc_path})
    elif args.command=='knowledge-status':
        result=client.call('/knowledge/status')
    elif args.command=='knowledge-refresh':
        result=client.call('/knowledge/refresh',{'full':args.full})
    elif args.command=='projects':
        result=client.call('/coding/projects')
    elif args.command=='code':
        result=client.call('/coding/submit',{'project_id':args.project,'objective':args.objective,
                                          'requirements':args.requirements,'workflow_id':args.workflow_id})
    elif args.command=='code-status':
        result=client.call('/coding/workflow/'+args.workflow_id)
    elif args.command in ('code-cancel','code-resume'):
        data={'workflow_id':args.workflow_id}
        if args.command=='code-resume':
            data['reason']=args.reason
        result=client.call('/coding/'+args.command.removeprefix('code-'),data)
    elif args.command=='submit':
        result=client.call('/submit',{'objective':args.objective,'requirements':args.requirements,
                                     'chapter_count':args.chapters})
    elif args.command=='status':
        result=client.call('/workflow/'+args.workflow_id)
    elif args.command=='cancel':
        result=client.call('/cancel',{'workflow_id':args.workflow_id})
    else:
        result=client.call('/health')
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
