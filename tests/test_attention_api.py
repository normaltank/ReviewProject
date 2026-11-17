"""API wire and audit tests use synthetic transport and never contact a service."""
from attention_browser import open_panel
import copy
import json
import tempfile
import unittest
import io
import urllib.error
from unittest.mock import patch
from pathlib import Path
from contextlib import closing

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate


class APITransport(unittest.TestCase):
    def test_prepared_json_wire_is_exactly_the_audited_request(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        from reviewproto.core import digest
        from reviewproto.local_io import encoded
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'感谢说明。'}],
                      'a_reference':{'version':'none','items':[]}})
            class FakeAPI(DeepSeekProvider):
                def complete(self, request):
                    self.sent=copy.deepcopy(request)
                    return {'choices':[{'message':{'content':'{"opinions":[],"relations":[],"unprocessed":[]}'},'finish_reason':'stop'}],
                            'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30,'prompt_cache_hit_tokens':2}}
            provider=FakeAPI(credential_loader=lambda:'SYNTHETIC-SECRET')
            run=generate(ws,'api-wire',provider)
            self.assertEqual(run['mode'],'remote_api')
            self.assertEqual(run['status'],'zero_candidates',run['errors'])
            call=run['calls'][0]
            self.assertEqual(call['request'],provider.sent)
            self.assertEqual(call['request_hash'],digest(encoded(provider.sent)))
            self.assertEqual(call['prompt_hash'],digest(provider.sent['messages'][0]['content'].encode()))
            self.assertEqual(provider.sent['model'],'deepseek-flash')
            self.assertEqual(provider.sent['response_format'],{'type':'json_object'})
            self.assertIn('"opinions"',provider.sent['messages'][0]['content'])
            self.assertEqual(provider.sent['thinking'],{'type':'enabled'})
            self.assertEqual(provider.sent['reasoning_effort'],'high')
            self.assertEqual(provider.sent['max_tokens'],32768)
            self.assertFalse({'temperature','seed','top_k','chat_template_kwargs','cache_prompt'} & provider.sent.keys())
            self.assertEqual(call['usage']['prompt_cache_hit_tokens'],2)
            self.assertNotIn('SYNTHETIC-SECRET',json.dumps(run))

    def test_transport_attaches_key_only_to_header_and_refuses_redirect_proxy_and_retry(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        from reviewproto.attention_provider import NoRedirect
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,n): return b'{"choices":[]}'
        with patch('reviewproto.attention_api_provider.urllib.request.build_opener') as build:
            build.return_value.open.return_value=Response()
            provider=DeepSeekProvider(credential_loader=lambda:'SYNTHETIC-SECRET')
            body=provider.prepare_request({'messages':[{'role':'system','content':'JSON'},{'role':'user','content':'{}'}],
                  'response_format':{'json_schema':{'schema':{'type':'object'}}}})
            self.assertEqual(provider.complete(body)['http_status'],200)
            req=build.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url,'https://api.deepseek.com/chat/completions')
            self.assertEqual(req.get_header('Authorization'),'Bearer SYNTHETIC-SECRET')
            self.assertNotIn(b'SYNTHETIC-SECRET',req.data)
            self.assertEqual(json.loads(req.data),body)
            self.assertEqual(build.call_args.args[0].proxies,{})
            self.assertIsInstance(build.call_args.args[1],NoRedirect)
            build.return_value.open.side_effect=urllib.error.HTTPError(req.full_url,302,'redirect',{},io.BytesIO(b'no redirect'))
            self.assertEqual(provider.complete(body)['http_status'],302)
            self.assertEqual(build.return_value.open.call_count,2)
            build.return_value.open.side_effect=RuntimeError('SYNTHETIC-SECRET')
            with self.assertRaisesRegex(Exception,'^E_ATTENTION_API_TRANSPORT$'): provider.complete(body)
            self.assertEqual(build.return_value.open.call_count,3)

    def test_endpoints_and_model_names_cannot_leak_credentials_to_other_hosts(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        for endpoint in ['http://api.deepseek.com','https://api.deepseek.com.evil','https://api.deepseek.com@evil',
                         'https://api.deepseek.com/?key=fake','https://api.deepseek.com:443','http://127.0.0.1:8767']:
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(Exception,'E_ATTENTION_API_ENDPOINT'):
                DeepSeekProvider(endpoint,credential_loader=lambda:self.fail('must not load'))
        for unsupported in ('handwritten','deepseek-v4-pro'):
            with self.assertRaisesRegex(Exception,'E_ATTENTION_API_MODEL'): DeepSeekProvider(model=unsupported)
        with self.assertRaisesRegex(Exception,'E_ATTENTION_API_MODEL'):
            DeepSeekProvider(credential_loader=lambda:self.fail('must not load')).complete({'model':'deepseek-v4-pro'})
        self.assertEqual(DeepSeekProvider(max_tokens=32768).config['max_tokens'],32768)
        self.assertEqual(DeepSeekProvider(max_tokens=8192).config['max_tokens'],8192)
        with self.assertRaisesRegex(Exception,'E_ATTENTION_CAPACITY'): DeepSeekProvider(max_tokens=32769)

    def test_secret_echo_is_not_persisted_as_raw_response(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        class Echo:
            status=401
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,n): return b'Unexpected header Bearer SYNTHETIC-SECRET'
        with patch('reviewproto.attention_api_provider.urllib.request.build_opener') as build:
            build.return_value.open.return_value=Echo()
            with self.assertRaisesRegex(Exception,'^E_ATTENTION_API_SECRET_RESPONSE$'):
                DeepSeekProvider(credential_loader=lambda:'SYNTHETIC-SECRET').complete({'model':'deepseek-flash'})

    def test_missing_key_is_late_bound_actionable_and_not_sent(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        from reviewproto.core import ReviewError
        def missing(): raise ReviewError('E_DEEPSEEK_CREDENTIAL_MISSING')
        provider=DeepSeekProvider(credential_loader=missing)
        with patch('reviewproto.attention_api_provider.urllib.request.build_opener') as build:
            with self.assertRaisesRegex(Exception,'E_DEEPSEEK_CREDENTIAL_MISSING'): provider.complete({'model':'deepseek-flash'})
            build.assert_not_called()

    def test_truncation_keeps_usage_raw_response_and_unprocessed_scope_without_retry(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'感谢说明。'}],
                      'a_reference':{'version':'none','items':[]}})
            class Truncated(DeepSeekProvider):
                def complete(self,request):
                    return {'raw_http_body':json.dumps({'choices':[{'message':{'content':'{"opinions":'},'finish_reason':'length'}],
                            'usage':{'completion_tokens':8192}}),'http_status':200}
            run=generate(ws,'truncated',Truncated(credential_loader=lambda:'fake'))
            self.assertEqual(run['status'],'failed')
            self.assertEqual(run['request_count'],1)
            self.assertEqual(run['calls'][0]['error'],'E_ATTENTION_RESPONSE_TRUNCATED')
            self.assertEqual(run['calls'][0]['usage'],{'completion_tokens':8192})
            self.assertIn('raw_http_body',run['calls'][0]['response'])
            self.assertTrue(run['unprocessed'])

    def test_prepare_failure_has_saved_call_and_unprocessed_scope(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'感谢说明。'}],
                      'a_reference':{'version':'none','items':[]}})
            class Broken(DeepSeekProvider):
                def prepare_request(self,request): raise RuntimeError('SYNTHETIC-PRIVATE-DETAIL')
                def complete(self,request): raise AssertionError('must not send')
            run=generate(ws,'prepare-fail',Broken(credential_loader=lambda:'fake'))
            self.assertEqual(run['status'],'failed')
            self.assertEqual(run['request_count'],0)
            self.assertEqual(run['calls'][0]['status'],'failed')
            self.assertEqual(run['calls'][0]['phase'],'prepare')
            self.assertTrue(run['unprocessed'])
            saved=(ws.path/'candidate-runs/prepare-fail/run.json').read_text(encoding='utf-8')
            self.assertNotIn('SYNTHETIC-PRIVATE-DETAIL',saved)

    def test_cli_resolves_model_by_provider_without_reading_credentials(self):
        from reviewproto.cli import main
        from reviewproto.attention_api_provider import DeepSeekProvider
        from reviewproto.attention_provider import LocalProvider
        from test_attention_candidate_ui import prepare
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';prepare(path)
            for flags,cls,model in [(['--provider','deepseek'],DeepSeekProvider,'deepseek-flash'),
                                    (['--provider','local'],LocalProvider,'reviewproject-qwen3-4b-q4km'),
                                    (['--local'],LocalProvider,'reviewproject-qwen3-4b-q4km')]:
                with self.subTest(flags=flags), patch('reviewproto.attention_candidates.generate') as generate_call:
                    generate_call.return_value={'status':'zero_candidates','mode':'remote_api' if cls is DeepSeekProvider else 'local_model','patch':{'edits':[]}}
                    self.assertEqual(main(['attention-generate','--workspace',str(path),'--run-id','cli']+flags),0)
                    provider=generate_call.call_args.args[2]
                    self.assertIsInstance(provider,cls)
                    self.assertEqual(provider.config['model'],model)
            import contextlib
            stderr=io.StringIO()
            with patch('reviewproto.attention_candidates.generate') as generate_call, contextlib.redirect_stderr(stderr):
                self.assertEqual(main(['attention-generate','--workspace',str(path),'--run-id','no-pro',
                                       '--provider','deepseek','--model','deepseek-v4-pro']),2)
                generate_call.assert_not_called()
            self.assertIn('deepseek-flash',stderr.getvalue())

    def test_json_mode_with_a_keeps_stages_and_only_selected_text_in_wire(self):
        from reviewproto.attention_api_provider import DeepSeekProvider
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'private-metadata-do-not-send','visibility':'author_visible',
                'text':'表格单位已经说明。','scores':[{'label':'原分','raw_value':'5'}]}],
                'a_reference':{'version':'synthetic-reference','items':[{'id':'unit','text':'表格单位应清楚。','locator':'synthetic/path'}]}})
            sent=[]
            class FakeAPI(DeepSeekProvider):
                def complete(self,request):
                    data=json.loads(request['messages'][1]['content']);sent.append(data)
                    if 'scopes' in data:
                        answer={'a_text':data['a_item']['text'],'comparisons':{
                            scope['id']:{'b_text':scope['text'],'kind':'explicit','reason':'双方具体对象均为表格单位。'} for scope in data['scopes']}}
                    elif 'selected' in data: answer={'function':'实质评价'}
                    else: answer={'opinions':[{'summary':'单位已说明','facets':[{'ref':'f1','focus':'表格单位已说明',
                                  'evidence':[{'section':'s1','passage':'p1'}],'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
                    return {'choices':[{'message':{'content':json.dumps(answer,ensure_ascii=False)},'finish_reason':'stop'}],
                            'model':'deepseek-flash','usage':{'prompt_tokens':1,'completion_tokens':2,'total_tokens':3}}
            run=generate(ws,'api-with-a',FakeAPI(credential_loader=lambda:'NEVER-READ'))
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            self.assertEqual([c['stage'] for c in run['calls']],['b_analysis','b_expression','a_mapping'])
            self.assertNotIn('a_item',sent[0]);self.assertNotIn('a_item',sent[1])
            self.assertNotIn('private-metadata-do-not-send',json.dumps(sent))
            self.assertNotIn('synthetic/path',json.dumps(sent))
            self.assertNotIn('scores',json.dumps(sent))
            self.assertEqual(run['patch']['edits'][0]['facets'][0]['a_links'][0]['status'],'needs_review')


    def test_api_preview_accept_and_chrome_do_not_claim_local_or_include_secret(self):
        import os
        from playwright.sync_api import sync_playwright
        from reviewproto.attention_api_provider import DeepSeekProvider
        from reviewproto.attention_candidate_service import CandidateSession
        from test_attention_candidate_ui import prepare
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';prepare(path)
            replies=iter([{'opinions':[{'summary':'有条件补充图例','facets':[{'ref':'f1','focus':'有记录时标明图例',
                          'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'}],
                          'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]},
                          {'function':'修改建议'}])
            class FakeAPI(DeepSeekProvider):
                def complete(self,request):
                    return {'choices':[{'message':{'content':json.dumps(next(replies),ensure_ascii=False)},'finish_reason':'stop'}]}
            session=CandidateSession(path)
            run=session.generate('api-full',FakeAPI(credential_loader=lambda:'SYNTHETIC-NEVER-READ'))
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            preview=session.preview('api-full')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'],headless=True)
                page=browser.new_page();page.goto(preview.as_uri())
                open_panel(page, 'candidate-audit')
                self.assertIn('DeepSeek API联网推理',page.locator('#candidate-preview').inner_text())
                self.assertNotIn('实际本机推理',page.locator('#candidate-preview').inner_text())
                self.assertNotIn('SYNTHETIC-NEVER-READ',page.content())
                page.locator('[id^="candidate-facet-"] summary').first.click()
                self.assertIn('若有记录',page.locator('body').inner_text())
                browser.close()
            self.assertEqual(session.accept('api-full',actor='synthetic editor',reason='engineering fixture')['revision'],1)
            self.assertEqual(CandidateSession(path).accept('api-full',actor='repeat',reason='idempotence')['revision'],1)
