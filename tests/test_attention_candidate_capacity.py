"""Local HTTP boundaries, capacity preflight and private reasoning separation."""
import json
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import LocalProvider, generate, accept
from reviewproto.attention_candidate_ui import CandidateSession


@contextmanager
def server_for(token_response=None, focused=False):
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path,body))
            if self.path=='/apply-template': response={'prompt':'complete formatted synthetic conversation'}
            elif self.path=='/tokenize': response=token_response
            else:
                stage=body['response_format']['json_schema']['name']
                if stage=='b_expression':
                    message={'content':json.dumps({'function':'礼貌致谢'},ensure_ascii=False),
                             'reasoning_content':'PRIVATE_REASONING_SENTINEL'}
                else:
                    facets=[{'ref':'f1','focus':'感谢修改','evidence':[{'section':'s1','passage':'p1'}],
                             'qualifiers':{},'themes':[]}]
                    answer={'opinions':[{'summary':'致谢','facets':facets}] if focused else [],'relations':[],'unprocessed':[]}
                    message={'content':json.dumps(answer,ensure_ascii=False)}
                response={'choices':[{'message':message,'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}
            self.send_response(200);self.end_headers()
            self.wfile.write(json.dumps(response,ensure_ascii=False).encode('utf-8'))
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)+'/v1',requests
    finally:server.shutdown();server.server_close();worker.join()


class CandidateCapacity(unittest.TestCase):
    def test_too_small_user_output_cap_is_rejected_without_raising_it(self):
        from reviewproto.core import ReviewError
        with server_for(focused=True) as (endpoint,requests), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'感谢修改。'}],
                      'a_reference':{'version':'none','items':[]}})
            with self.assertRaisesRegex(ReviewError,'E_ATTENTION_CAPACITY_PROFILE'):
                generate(ws,'small-cap',LocalProvider(endpoint,max_tokens=512))
            self.assertEqual(requests,[])
            self.assertEqual(ws.state()['opinions'],[])

    def test_long_source_uses_exact_local_tokens_without_truncating_input(self):
        original=('应保留不同数据的年份说明，并明确各批资料的适用范围。'*45)[:1000]
        with server_for({'tokens':[1]*3000}) as (endpoint,requests), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'long','visibility':'author_visible','text':original}],
                      'a_reference':{'version':'none','items':[]}})
            run=generate(ws,'long',LocalProvider(endpoint))
            self.assertEqual(run['status'],'zero_candidates',run['errors'])
            self.assertEqual([path for path,_ in requests],['/apply-template','/tokenize','/v1/chat/completions'])
            actual=json.loads(requests[-1][1]['messages'][1]['content'])
            self.assertEqual(actual['sections'][0]['text'],original)
            self.assertEqual(run['request_count'],1);self.assertEqual(run['capacity_request_count'],2)
            audit=run['calls'][0]['capacity']
            self.assertGreater(audit['request_utf8_bytes']+4096+256,16384)
            self.assertEqual(audit['prompt_tokens'],3000)
            self.assertEqual(audit['total_tokens_bound'],7352)
            self.assertIn('raw_http_body',audit['calls'][1]['response'])
            self.assertEqual(ws.state()['opinions'],[])

    def test_true_overflow_or_failed_preflight_never_sends_completion(self):
        original=('各批资料应说明年份和适用范围，不把同一条记录当成多个样本。'*45)[:1000]
        for token_response,code in [({'tokens':[1]*16000},'E_ATTENTION_CAPACITY'),
                                    ({'tokens':'invalid'},'E_ATTENTION_CAPACITY_CHECK')]:
            with self.subTest(code=code), server_for(token_response) as (endpoint,requests), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
                ws.build({'schema':'attention-input/1','records':[{'anchor':'long','visibility':'author_visible','text':original}],
                          'a_reference':{'version':'none','items':[]}})
                run=generate(ws,'blocked',LocalProvider(endpoint))
                self.assertEqual(run['status'],'failed')
                self.assertEqual([path for path,_ in requests],['/apply-template','/tokenize'])
                self.assertEqual(run['request_count'],0);self.assertEqual(run['capacity_request_count'],2)
                self.assertEqual(run['errors'][0]['code'],code)
                self.assertTrue(run['unprocessed'])
                self.assertEqual(run['snapshot']['records'][0]['text'],original)

    def test_stage_thinking_budgets_and_trace_stay_private(self):
        with server_for(focused=True) as (endpoint,requests), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'感谢修改。'}],
                      'a_reference':{'version':'none','items':[]}})
            run=generate(ws,'private',LocalProvider(endpoint))
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            extraction,function=[body for path,body in requests if path=='/v1/chat/completions']
            self.assertTrue(extraction['chat_template_kwargs']['enable_thinking'])
            self.assertEqual(extraction['reasoning_budget_tokens'],512)
            self.assertEqual(extraction['temperature'],0.6)
            self.assertTrue(function['chat_template_kwargs']['enable_thinking'])
            self.assertEqual(function['reasoning_budget_tokens'],256)
            self.assertEqual((function['temperature'],function['top_p'],function['top_k'],function['min_p'],function['seed']),(0.6,0.95,20,0,42))
            self.assertGreaterEqual(function['max_tokens'],768)
            self.assertIn('PRIVATE_REASONING_SENTINEL',run['calls'][1]['response']['raw_http_body'])
            self.assertNotIn('PRIVATE_REASONING_SENTINEL',json.dumps(run['patch']))
            page=CandidateSession(ws.path).preview('private').read_text(encoding='utf-8')
            self.assertNotIn('PRIVATE_REASONING_SENTINEL',page)
            saved=accept(ws,'private',actor='editor',reason='inspect')
            self.assertNotIn('PRIVATE_REASONING_SENTINEL',json.dumps(saved['opinions']))
