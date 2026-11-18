"""One local browser workbench, reusing the input, candidate and apply engines."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, urlencode
import secrets
import threading
import uuid

from .attention import AttentionWorkspace
from .attention_input import AttentionInput, build_prepared, import_prepared_a
from .attention_candidate_service import CandidateSession
from .attention_candidate_render import render_candidate_preview
from .attention_api_provider import DeepSeekProvider
from .attention_render import render
from .local_io import checked_local, load_json, atomic, encoded
from .core import require, ReviewError


class Workbench:
    def __init__(self, data_dir, port=0, *, provider_factory=None):
        self.data_dir=checked_local(data_dir); self.data_dir.mkdir(parents=True,exist_ok=True)
        self.token=secrets.token_urlsafe(32)
        self.projects={}; self.jobs={}; self.lock=threading.RLock()
        self.provider_factory=provider_factory
        self.stopping=False
        self.closed=threading.Event()
        app=self
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(10)
                super().setup()

            def log_message(self,*args): pass
            def respond(self,status,payload,kind='application/json'):
                raw=payload.encode('utf-8') if isinstance(payload,str) else encoded(payload)
                self.send_response(status)
                for key,value in [('Content-Type',kind+'; charset=utf-8'),('Content-Length',str(len(raw))),
                                  ('Cache-Control','no-store'),('Referrer-Policy','no-referrer'),('X-Content-Type-Options','nosniff')]:
                    self.send_header(key,value)
                try:
                    self.end_headers(); self.wfile.write(raw)
                except ConnectionError:
                    pass  # A navigation can abandon a completed local request.
            def do_GET(self):
                if self.headers.get('Host')!=app.authority: return self.respond(403,{'error':'E_ATTENTION_SESSION'})
                route=urlsplit(self.path); query=parse_qs(route.query)
                try:
                    if route.path in ('/','/workbench'):
                        html=Path(__file__).with_name('workbench.html').read_text(encoding='utf-8')
                        return self.respond(200,html.replace('__WORKBENCH_TOKEN__',app.token),'text/html')
                    if route.path in ('/workbench.js','/workbench.css'):
                        return self.respond(200,Path(__file__).with_name(route.path[1:]).read_text(encoding='utf-8'),
                            'text/javascript' if route.path.endswith('.js') else 'text/css')
                    if route.path=='/health': return self.respond(200,{'status':'stopping' if app.stopping else 'ready'})
                    if route.path=='/api/configuration':
                        from .credential import credential_status
                        return self.respond(200,credential_status())
                    if route.path in ('/result','/preview'):
                        key = query.get('id', [''])[0]
                        with app.lock:
                            require(not app.stopping, 'E_WORKBENCH_STOPPING')
                            project = app.project(key)
                            if route.path == '/result':
                                session = {'token': project['token'], 'workbench_url': '/workbench?' + urlencode({'project': key})}
                                html = render(app.state(project), session=session)
                            else:
                                run = query.get('run', [''])[0]
                                session = app.candidate_session(project)
                                require(run in session.runs(), 'E_ATTENTION_RUN')
                                html = render_candidate_preview(session.inspect(run),
                                    workbench_url='/workbench?' + urlencode({'project': key, 'run': run}),
                                    result_url='/result?' + urlencode({'id': key}))
                        return self.respond(200, html, 'text/html')
                    return self.respond(404,{'error':'E_NOT_FOUND'})
                except Exception as exc: self.failure(exc)
            def failure(self,exc):
                code=str(exc) if isinstance(exc,ReviewError) else 'E_WORKBENCH_REQUEST'
                self.respond(409,{'error':code})
            def do_POST(self):
                self.close_connection = True
                if self.headers.get('Host') != app.authority or self.headers.get('Origin') != app.origin:
                    return self.respond(403, {'error': 'E_ATTENTION_SESSION'})
                token = self.headers.get('X-Attention-Token', '')
                with app.lock:
                    project = next((p for p in app.projects.values() if secrets.compare_digest(token, p['token'])), None) if self.path == '/save' else None
                authorized = project is not None if self.path == '/save' else secrets.compare_digest(token, app.token)
                if not authorized:
                    return self.respond(403, {'error': 'E_ATTENTION_SESSION'})
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not (0 < size <= 10_000_000 and not self.headers.get('Transfer-Encoding') and
                            self.headers.get('Content-Type', '').split(';')[0] == 'application/json'):
                        raise ValueError('request')
                    payload = load_json(self.rfile.read(size))
                    if not isinstance(payload, dict) or (project and
                            (payload.get('schema') != 'attention-patch/2' or payload.get('analysis_id') != project['analysis_id'])):
                        raise ValueError('request')
                except (ValueError, OSError, ReviewError):
                    return self.respond(400, {'error': 'E_ATTENTION_REQUEST'})
                try:
                    with app.lock:
                        require(not app.stopping, 'E_WORKBENCH_STOPPING')
                        if project:
                            with closing(AttentionWorkspace(project['path'])) as ws:
                                require(ws.state()['analysis_id'] == project['analysis_id'], 'E_ATTENTION_TARGET')
                                result = {'revision': ws.apply(payload)['revision']}
                        elif self.path == '/api/stop':
                            require(not any(j['status'] == 'running' for j in app.jobs.values()), 'E_WORKBENCH_BUSY')
                            app.stopping = True
                            result = {'status': 'stopping'}
                        else:
                            result = app.action(self.path, payload)
                    try:
                        self.respond(200, result)
                    finally:
                        if self.path == '/api/stop':
                            threading.Thread(target=app.finish_close, daemon=False).start()
                except Exception as exc:
                    if self.path == '/save' and not isinstance(exc, ReviewError):
                        return self.respond(500, {'error': 'E_ATTENTION_SAVE'})
                    self.failure(exc)
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.server.daemon_threads = False
        self.authority='127.0.0.1:'+str(self.server.server_port); self.origin='http://'+self.authority; self.url=self.origin+'/'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()

    def project(self,key):
        require(key in self.projects,'E_ATTENTION_TARGET'); return self.projects[key]

    def state(self,project):
        with closing(AttentionWorkspace(project['path'])) as ws:
            state=ws.state(); require(state['analysis_id']==project['analysis_id'],'E_ATTENTION_TARGET'); return state

    def open(self,path):
        path=checked_local(path); require((path/'attention.sqlite3').is_file(),'E_ATTENTION_EMPTY')
        with closing(AttentionWorkspace(path)) as ws: state=ws.state()
        key=next((k for k,p in self.projects.items() if p['path']==path),uuid.uuid4().hex)
        if key in self.projects:
            require(self.projects[key]['analysis_id']==state['analysis_id'],'E_ATTENTION_TARGET')
        self.projects.setdefault(key,{'path':path,'token':secrets.token_urlsafe(32),'analysis_id':state['analysis_id']})
        recent=self.recents(); recent=[str(path)]+[p for p in recent if p!=str(path)]
        atomic(self.data_dir/'recent.json',encoded(recent[:30]))
        return {'id':key,'path':str(path),'state':state,'url':'/result?id='+key}

    def recents(self):
        try: return load_json((self.data_dir/'recent.json').read_bytes())
        except FileNotFoundError: return []

    def draft(self,payload):
        draft=AttentionInput()
        for index,record in enumerate(payload.get('records',[])):
            if record.get('kind') == 'workspace':
                require(isinstance(record.get('source_selection'), dict), 'E_ATTENTION_REVALIDATION')
                draft.add_workspace(record['workspace'], record['section_id'], record.get('paper_id', ''),
                                    expected=record['source_selection'])
            else: draft.add_transcription(record.get('anchor') or 'B'+str(index+1),record['text'],record.get('visibility','author_visible'),
                record.get('scores',[]),record.get('locator') or '网页录入 '+str(index+1),record.get('paper_id',''))
        if payload.get('a_reference', {}).get('items'): draft.set_a(payload['a_reference'])
        return draft

    def action(self,route,payload):
        if route=='/api/home':
            from .credential import credential_status
            draft=self.data_dir/'input-draft.json'
            return {'recent':self.recents(),'data_dir':str(self.data_dir),
                    'configuration':credential_status(),
                    'draft':load_json(draft.read_bytes()) if draft.is_file() else None,
                    'jobs':[self.job_status(j) for j in self.jobs.values()]}
        if route=='/api/draft':
            atomic(self.data_dir/'input-draft.json',encoded(payload)); return {'saved':True}
        if route=='/api/browse':
            path=checked_local(payload.get('path') or self.data_dir)
            return {'path':str(path),'parent':str(path.parent),'directories':sorted(str(p) for p in path.iterdir() if p.is_dir()),
                    'analysis':(path/'attention.sqlite3').is_file()}
        if route=='/api/source':
            path = checked_local(payload['path'])
            return {'path': str(path), 'sections': AttentionInput.workspace_options(path)}
        if route=='/api/sample':
            from .workbench_sample import create_sample
            path=self.data_dir/('synthetic-example-'+uuid.uuid4().hex)
            create_sample(path); return self.open(path)
        if route=='/api/create':
            build_prepared(self.draft(payload),payload['path']); return self.open(payload['path'])
        if route=='/api/open': return self.open(payload['path'])
        if route=='/api/credential':
            from .credential import save_deepseek_key
            save_deepseek_key(payload['key']); return {'configured':True}
        if route=='/api/job': return self.job_status(self.jobs[payload['job']])
        project=self.project(payload.get('id'))
        self.state(project)  # Detect a directory replaced by a different package.
        if route=='/api/state': return self.open(project['path'])
        if route=='/api/recover':
            with closing(AttentionWorkspace(project['path'])) as ws:
                require(ws.state()['analysis_id'] == project['analysis_id'], 'E_ATTENTION_TARGET')
                ws.recover()
            return self.open(project['path'])
        if route=='/api/import-a':
            with closing(AttentionWorkspace(project['path'])) as ws:
                require(ws.state()['analysis_id'] == project['analysis_id'] == payload.get('analysis_id'),
                        'E_ATTENTION_TARGET')
                import_prepared_a(ws,payload['a_reference'],payload.get('actor','网页使用者'),payload.get('reason','显式更换A参照'))
            return self.open(project['path'])
        if route=='/api/runs':
            session = self.candidate_session(project)
            return {'runs': [self.candidate_status(session, run) for run in session.runs()]}
        if route=='/api/preview':
            session=self.candidate_session(project); require(payload['run'] in session.runs(),'E_ATTENTION_RUN')
            run = session.inspect(payload['run'])
            return {'run':run,'url':'/preview?id='+payload['id']+'&run='+payload['run']}
        if route=='/api/accept':
            session=self.candidate_session(project); require(payload['run'] in session.runs(),'E_ATTENTION_RUN')
            session.accept(payload['run'],actor=payload.get('actor','网页使用者'),reason=payload.get('reason','核对待保存结果后显式接收'))
            return self.open(project['path'])
        if route=='/api/generate':
            require(not any(j['project']==payload['id'] and j['status']=='running' for j in self.jobs.values()),'E_WORKBENCH_BUSY')
            session=self.candidate_session(project)
            provider=self.provider_factory() if self.provider_factory else DeepSeekProvider()
            if not self.provider_factory:
                from .credential import load_deepseek_key
                load_deepseek_key()  # Fail before scheduling; never put secret in job state.
            key=uuid.uuid4().hex; run='web-'+key
            job={'id':key,'project':payload['id'],'path':str(project['path']),'run':run,'status':'running',
                 'revision':session.snapshot['revision'],'records':payload.get('records'),'phase':'正在分析所选原话'}
            self.jobs[key]=job
            def worker():
                try:
                    result=session.generate(run,provider,payload.get('records'))
                    with self.lock:
                        job.update(status=result['status'],
                            completed_records=len(result.get('coverage',[])),requests=len(result.get('calls',[])))
                except Exception as exc:
                    with self.lock: job.update(status='failed',phase='分析未完成，保留已产生的候选记录',error=str(exc) if isinstance(exc,ReviewError) else 'E_WORKBENCH_JOB')
            job['thread']=threading.Thread(target=worker,daemon=False); job['thread'].start()
            return self.job_status(job)
        raise ReviewError('E_NOT_FOUND')

    def candidate_session(self, project):
        session = CandidateSession(project['path'])
        require(session.snapshot['analysis_id'] == project['analysis_id'], 'E_ATTENTION_TARGET')
        return session

    def candidate_status(self, session, run_id):
        try:
            run = session.inspect(run_id)
        except (OSError, ValueError, ReviewError, TypeError, KeyError):
            return {'run': run_id, 'state': 'unavailable', 'preview': False}
        active = any(job['run'] == run_id and job['status'] == 'running' for job in self.jobs.values())
        if active:
            state = 'running'
        elif run.get('accepted_revision') is not None:
            state = 'accepted'
        elif run['validity'] != 'current':
            state = 'stale'
        elif run['status'] in {'complete', 'partial'} and run['patch']['edits']:
            state = run['status']
        else:
            state = 'interrupted' if run['status'] == 'running' else run['status']
        return {'run': run_id, 'state': state, 'preview': True,
                'accepted_revision': run.get('accepted_revision'), 'revision': run['snapshot']['revision']}

    def job_status(self,job):
        result={k:v for k,v in job.items() if k!='thread'}
        path=Path(job['path'])/'candidate-runs'/job['run']/'run.json'
        if job['status']=='running' and path.is_file():
            try:
                run=load_json(path.read_bytes()); result['completed_records']=len(run.get('coverage',[])); result['requests']=len(run.get('calls',[]))
            except (ValueError,OSError): pass
        if job['status'] != 'running':
            try:
                session = self.candidate_session(self.project(job['project']))
                result['candidate'] = self.candidate_status(session, job['run'])
            except (OSError, ReviewError):
                result['candidate'] = {'run': job['run'], 'state': 'unavailable', 'preview': False}
        return result

    def close(self):
        with self.lock:
            already_stopping = self.stopping
            self.stopping = True
        if already_stopping:
            self.closed.wait()
        else:
            self.finish_close()

    def finish_close(self):
        try:
            self.server.shutdown(); self.server.server_close(); self.thread.join()
            for job in self.jobs.values(): job['thread'].join()
        finally: self.closed.set()

    def __enter__(self): return self
    def __exit__(self,*args): self.close()
