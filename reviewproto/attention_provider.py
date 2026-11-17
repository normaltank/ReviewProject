"""Bounded local chat-completions transport and explicit engineering replay."""
import copy
import json
import urllib.error
import urllib.parse
import urllib.request
from .core import require, ReviewError, digest
from .local_io import encoded

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
        source_bound=any('focus' in f for op in first.get('opinions',[]) for f in op.get('facets',[]))
        focused=source_bound and any('state' not in f for op in first.get('opinions',[]) for f in op.get('facets',[]))
        self.config = {'provider':'injected-replay/1','protocol':('attention-semantic/5' if focused else 'attention-semantic/3' if source_bound else 'attention-semantic/2') if 'opinions' in first else 'attention-canonical-replay/1'}

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
        from .local_model_profiles import profile, catalog_hash
        selected = profile(model)
        self.config = {'endpoint':endpoint.rstrip('/'), 'model':model, 'profile_id':model,
            'profile_catalog_sha256':catalog_hash(), 'model_identity':{key:selected[key] for key in
                ('filename','size','sha256','publisher','revision','source','license') if key in selected},
            'max_tokens':max_tokens, 'timeout':timeout, 'context_tokens':selected['context_tokens'],
            **selected['sampling'], 'stage_profiles':selected['stage_profiles']}

    def complete(self, request):
        return self._post('/v1/chat/completions',request)

    def _post(self, route, body):
        require(route in {'/v1/chat/completions','/apply-template','/tokenize'},'E_ATTENTION_ENDPOINT')
        req = urllib.request.Request(self.config['endpoint'].removesuffix('/v1') + route, data=encoded(body), headers={'Content-Type':'application/json'}, method='POST')
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

    def count_prompt(self, request, audit):
        """Local, non-inference preflight; persist both literal endpoint replies."""
        audit.update(method='llama.cpp-template-tokenize/1',calls=[])
        def post(route,payload):
            call={'route':route,'request':copy.deepcopy(payload),'request_hash':digest(encoded(payload)),'status':'pending'}
            audit['calls'].append(call)
            response=self._post(route,payload)
            call.update(response=response,response_hash=digest(encoded(response)))
            require(response['http_status']==200,'E_ATTENTION_CAPACITY_CHECK')
            parsed=json.loads(response['raw_http_body'])
            call['status']='complete'
            return parsed
        try:
            template=post('/apply-template',request)
            require(isinstance(template,dict) and isinstance(template.get('prompt'),str),'E_ATTENTION_CAPACITY_CHECK')
            tokenized=post('/tokenize',{'content':template['prompt'],'add_special':False,'parse_special':True})
            require(isinstance(tokenized,dict) and isinstance(tokenized.get('tokens'),list) and
                all(type(token) is int for token in tokenized['tokens']),'E_ATTENTION_CAPACITY_CHECK')
            audit['prompt_tokens']=len(tokenized['tokens'])
            return audit['prompt_tokens']
        except Exception as exc:
            audit['error']='E_ATTENTION_CAPACITY_CHECK'
            if audit['calls']:audit['calls'][-1]['status']='failed'
            raise ReviewError('E_ATTENTION_CAPACITY_CHECK') from exc
