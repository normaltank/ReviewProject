"""Explicit DeepSeek API transport; never used as a local provider fallback."""
import copy
import json
import urllib.error
import urllib.request

from .core import require, ReviewError
from .local_io import encoded
from .attention_provider import NoRedirect

API_ENDPOINT = 'https://api.deepseek.com'
API_MODELS = ('deepseek-flash',)
API_DEFAULT_TOKENS = 32768


class DeepSeekProvider:
    mode = 'remote_api'

    def __init__(self, endpoint=API_ENDPOINT, model=API_MODELS[0], max_tokens=API_DEFAULT_TOKENS,
                 timeout=600, *, credential_loader=None):
        require(endpoint in {API_ENDPOINT,API_ENDPOINT+'/',API_ENDPOINT+'/v1',API_ENDPOINT+'/v1/'},'E_ATTENTION_API_ENDPOINT')
        require(model in API_MODELS,'E_ATTENTION_API_MODEL')
        require(type(max_tokens) is int and 1 <= max_tokens <= 32768 and
                isinstance(timeout,(int,float)) and 0 < timeout <= 600,'E_ATTENTION_CAPACITY')
        from .credential import load_deepseek_key
        self._credential_loader = credential_loader or load_deepseek_key
        self.config = {'provider':'deepseek-api/1','endpoint':API_ENDPOINT,'model':model,
                       'max_tokens':max_tokens,'timeout':timeout,'context_tokens':1_000_000,
                       'thinking':{'type':'enabled'},'reasoning_effort':'high',
                       'response_format':{'type':'json_object'}}

    def prepare_request(self, request):
        """Called before audit hashing. complete() sends this exact JSON body."""
        require(self.config['model'] in API_MODELS,'E_ATTENTION_API_MODEL')
        result={'messages':copy.deepcopy(request['messages'])}
        schema=request['response_format']['json_schema']['schema']
        result['messages'][0]['content']+='\nReturn exactly one JSON object satisfying this complete JSON schema. No Markdown or commentary.\n'+json.dumps(schema,ensure_ascii=False,separators=(',',':'))
        result.update(model=self.config['model'],max_tokens=self.config['max_tokens'],
                      thinking=copy.deepcopy(self.config['thinking']),reasoning_effort='high',
                      response_format={'type':'json_object'})
        return result

    def complete(self, request):
        try:
            require(request.get('model') in API_MODELS,'E_ATTENTION_API_MODEL')
            key=self._credential_loader()
            require(isinstance(key,str) and bool(key.strip()) and key.isascii() and
                    not any(c.isspace() for c in key),'E_DEEPSEEK_CREDENTIAL_MISSING')
            req=urllib.request.Request(API_ENDPOINT+'/chat/completions',data=encoded(request),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            try:
                with opener.open(req,timeout=self.config['timeout']) as response:
                    raw=response.read(10_000_001);status=response.status
            except urllib.error.HTTPError as response:
                with response:
                    raw=response.read(10_000_001);status=response.code
            require(len(raw)<=10_000_000,'E_ATTENTION_LIMIT')
            body=raw.decode('utf-8',errors='replace')
            # Unexpected credential echoes are never persisted as a raw response.
            require(key not in body,'E_ATTENTION_API_SECRET_RESPONSE')
            return {'raw_http_body':body,'http_status':status}
        except ReviewError as exc:
            if str(exc) in {'E_ATTENTION_API_MODEL','E_DEEPSEEK_CREDENTIAL_MISSING','E_DEEPSEEK_CREDENTIAL_STORE',
                            'E_ATTENTION_LIMIT','E_ATTENTION_API_SECRET_RESPONSE'}:
                raise
            raise ReviewError('E_ATTENTION_API_TRANSPORT') from None
        except Exception:
            raise ReviewError('E_ATTENTION_API_TRANSPORT') from None
