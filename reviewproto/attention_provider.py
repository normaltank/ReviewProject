"""Bounded local chat-completions transport and explicit engineering replay."""
import copy
import json
import urllib.error
import urllib.parse
import urllib.request
from .core import require
from .store import encoded

class ReplayProvider:
    mode = 'replay'

    def __init__(self, responses):
        responses=copy.deepcopy(list(responses))
        first=responses[0] if responses else {}
        try:
            if 'raw_http_body' in first: first=json.loads(first['raw_http_body'])
            if 'choices' in first: first=json.loads(first['choices'][0]['message']['content'])
        except (ValueError,KeyError,TypeError,IndexError): first={}
        self.responses = iter(responses)
        self.config = {'provider':'injected-replay/1','protocol':'attention-semantic/2' if 'opinions' in first else 'attention-canonical-replay/1'}

    def complete(self, request):
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        if 'choices' in result or 'raw_http_body' in result:
            return result
        return {'choices':[{'message':{'content':json.dumps(result, ensure_ascii=False)},'finish_reason':'stop'}], 'usage':None}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class LocalProvider:
    mode = 'local_model'

    def __init__(self, endpoint='http://127.0.0.1:8766/v1', model='reviewproject-qwen3-4b-q4km', max_tokens=4096, timeout=180):
        parsed = urllib.parse.urlsplit(endpoint)
        require(parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment and parsed.path.rstrip('/') == '/v1', 'E_ATTENTION_ENDPOINT')
        require(parsed.netloc == '127.0.0.1' or parsed.netloc == '127.0.0.1:' + str(parsed.port), 'E_ATTENTION_ENDPOINT')
        require(type(max_tokens) is int and 1 <= max_tokens <= 8192 and isinstance(timeout,(int,float)) and 0 < timeout <= 600, 'E_ATTENTION_CAPACITY')
        require(isinstance(model,str) and model.strip(), 'E_ATTENTION_MODEL')
        self.config = {'endpoint':endpoint.rstrip('/'), 'model':model, 'max_tokens':max_tokens, 'timeout':timeout, 'context_tokens':16384}

    def complete(self, request):
        body = request
        req = urllib.request.Request(self.config['endpoint'] + '/chat/completions', data=encoded(body), headers={'Content-Type':'application/json'}, method='POST')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(req, timeout=self.config['timeout']) as response:
                raw = response.read(10_000_001)
                status = response.status
        except urllib.error.HTTPError as response:
            with response:
                raw = response.read(10_000_001)
                status = response.code
        require(len(raw) <= 10_000_000, 'E_ATTENTION_LIMIT')
        # Keep literal bytes as UTF-8 text, alongside parsed response in the run.
        return {'raw_http_body':raw.decode('utf-8',errors='replace'),'http_status':status}
