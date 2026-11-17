"""Temporary loopback editing session, permanently bound to one analysis package."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from .attention import AttentionWorkspace
from .attention_render import render
from .core import ReviewError


class AttentionSession:
    def __init__(self, path):
        self._path = Path(path).resolve()
        with closing(AttentionWorkspace(self._path)) as ws:
            self._analysis_id = ws.state()['analysis_id']
        self.token = secrets.token_urlsafe(32)
        session = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log material, tokens or requests.

            def respond(self, status, payload, content_type='application/json'):
                raw = payload.encode('utf-8') if isinstance(payload, str) else json.dumps(payload).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', content_type + '; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.headers.get('Host') != session.authority:
                    return self.respond(403, {'error':'E_ATTENTION_SESSION'})
                if self.path != '/':
                    return self.respond(404, {'error':'E_NOT_FOUND'})
                try:
                    with closing(AttentionWorkspace(session._path)) as ws:
                        state = ws.state()
                        if state['analysis_id'] != session._analysis_id:
                            raise ReviewError('E_ATTENTION_TARGET')
                    self.respond(200, render(state, session={'token':session.token}), 'text/html')
                except Exception:
                    self.respond(409, {'error':'E_ATTENTION_TARGET'})

            def do_POST(self):
                self.close_connection = True
                if (self.path != '/save' or self.headers.get('Host') != session.authority or
                        self.headers.get('Origin') != session.origin or
                        not secrets.compare_digest(self.headers.get('X-Attention-Token', ''), session.token)):
                    return self.respond(403, {'error':'E_ATTENTION_SESSION'})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    length = 0
                if (not 0 < length <= 10_000_000 or self.headers.get('Transfer-Encoding') or
                        self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
                    return self.respond(400, {'error':'E_ATTENTION_REQUEST'})
                try:
                    self.connection.settimeout(10)
                    raw = self.rfile.read(length)
                    def pairs(items):
                        result = {}
                        for key, value in items:
                            if key in result: raise ValueError('duplicate')
                            result[key] = value
                        return result
                    patch = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(patch, dict) or patch.get('schema') != 'attention-patch/2' or patch.get('analysis_id') != session._analysis_id:
                        raise ValueError('patch')
                except Exception:
                    return self.respond(400, {'error':'E_ATTENTION_REQUEST'})
                try:
                    with closing(AttentionWorkspace(session._path)) as ws:
                        if ws.state()['analysis_id'] != session._analysis_id:
                            raise ReviewError('E_ATTENTION_TARGET')
                        state = ws.apply(patch)
                    self.respond(200, {'revision':state['revision']})
                except ReviewError as exc:
                    self.respond(409, {'error':str(exc)})
                except Exception:
                    self.respond(500, {'error':'E_ATTENTION_SAVE'})

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._server.daemon_threads = False
        self.authority = '127.0.0.1:' + str(self._server.server_port)
        self.origin = 'http://' + self.authority
        self.url = self.origin + '/'
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
