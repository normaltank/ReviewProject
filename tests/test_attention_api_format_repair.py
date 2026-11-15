"""Bounded format-only repair through fake HTTP; no real key or API access."""
import copy
import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_api_provider import DeepSeekProvider
from reviewproto.attention_candidates import generate
from reviewproto.core import digest
from reviewproto.store import encoded

USAGE={'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}
B={'opinions':[{'summary':'说明已完成','facets':[{'ref':'f1','focus':'单位已经说明',
   'evidence':[{'section':'s1','passage':'p1'}],'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}


def reply(value, *, usage=USAGE, finish='stop', status=200):
    body={'choices':[{'message':{'content':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)},'finish_reason':finish}]}
    if usage is not None: body['usage']=usage
    return status,json.dumps(body,ensure_ascii=False).encode()


class FormatRepair(unittest.TestCase):
    def execute(self,replies,*,provider=None,a=False):
        sent=[];responses=iter(replies)
        def open_fake(request,**kwargs):
            sent.append(json.loads(request.data))
            response=next(responses)
            if isinstance(response,Exception): raise response
            status,body=response
            if status!=200: raise urllib.error.HTTPError(request.full_url,status,'synthetic',{},io.BytesIO(body))
            stream=io.BytesIO(body);stream.status=status
            return stream
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'DO_NOT_SEND_METADATA',
                'visibility':'author_visible','text':'单位已经说明。','scores':[{'label':'原分','raw_value':'5'}]}],
                'a_reference':{'version':'synthetic','items':[{'id':'a','text':'A_REFERENCE_SENTINEL','locator':'DO_NOT_SEND_PATH'}] if a else []}})
            formal={p.name:p.read_bytes() for p in ws.path.iterdir() if p.is_file()}
            with patch('reviewproto.attention_api_provider.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect=open_fake
                run=generate(ws,'format',provider or DeepSeekProvider(credential_loader=lambda:'FAKE-KEY'),context_chars=24000)
            for name,before in formal.items(): self.assertEqual((ws.path/name).read_bytes(),before,name)
            saved=json.loads((ws.path/'candidate-runs/format/run.json').read_text())
            self.assertEqual(saved,run)
            self.assertNotIn('FAKE-KEY',json.dumps(run))
            return run,sent

    def test_invalid_json_gets_one_repair_and_keeps_first_failure_partial(self):
        invalid='{"opinions":['
        run,sent=self.execute([reply(invalid),reply(B),reply({'function':'实质评价'})])
        self.assertEqual(run['status'],'partial',run['errors'])
        self.assertEqual(len(run['patch']['edits']),1)
        self.assertEqual(run['request_count'],3)
        self.assertEqual(run['format_repair_count'],1)
        first,repair=run['calls'][:2]
        self.assertEqual(first['status'],'failed')
        self.assertEqual(first['error'],'E_ATTENTION_JSON_FORMAT')
        self.assertEqual(repair['purpose'],'format_repair')
        self.assertEqual(repair['parent_call_id'],first['call_id'])
        self.assertEqual(sent[0]['messages'][:2],sent[1]['messages'][:2])
        self.assertEqual(sent[1]['messages'][2],{'role':'assistant','content':invalid})
        self.assertEqual(sent[0]['max_tokens'],sent[1]['max_tokens'])
        for call,wire in zip(run['calls'],sent):
            self.assertEqual(call['request'],wire)
            self.assertEqual(call['request_hash'],digest(encoded(wire)))
            self.assertEqual(call['usage'],USAGE)

    def test_extra_field_is_schema_failure_then_one_valid_repair(self):
        invalid=copy.deepcopy(B);invalid['unrequested']='not part of schema'
        run,sent=self.execute([reply(invalid),reply(B),reply({'function':'实质评价'})])
        self.assertEqual(run['status'],'partial')
        self.assertEqual(run['calls'][0]['error'],'E_ATTENTION_SCHEMA_FORMAT')
        self.assertEqual(run['calls'][0]['status'],'failed')
        self.assertEqual(len(sent),3)
        self.assertIn('schema_validation',run['calls'][0])

    def test_second_bad_output_stops_and_reports_source_without_third_attempt(self):
        run,sent=self.execute([reply('{'),reply('{')])
        self.assertEqual(len(sent),2)
        self.assertEqual(run['status'],'failed')
        self.assertEqual(len(run['errors']),2)
        self.assertTrue(run['unprocessed'])
        self.assertEqual(run['patch']['edits'],[])

    def test_non_format_failures_and_unknown_usage_do_not_repair(self):
        for response in (reply('{',status=401),reply('{',status=429),reply('{',status=503),reply('{',finish='length'),reply('{',usage=None),reply('{',usage={}),TimeoutError('FAKE-KEY')):
            with self.subTest(response=type(response).__name__):
                run,sent=self.execute([response])
                self.assertEqual(len(sent),1)
                self.assertEqual(run['status'],'failed')
        class Broken(DeepSeekProvider):
            def prepare_request(self,request): raise RuntimeError('PRIVATE-PREPARE')
        run,sent=self.execute([],provider=Broken(credential_loader=lambda:'FAKE-KEY'))
        self.assertEqual(sent,[])
        self.assertEqual(len(run['calls']),1)
        self.assertEqual(run['calls'][0]['phase'],'prepare')

    def test_b_repair_does_not_receive_a_scores_or_paths(self):
        a={'a_text':'A_REFERENCE_SENTINEL','comparisons':{'b1':{'b_text':'单位已经说明。','kind':'unrelated','reason':'对象不同。'}}}
        run,sent=self.execute([reply('{'),reply(B),reply({'function':'实质评价'}),reply(a)],a=True)
        self.assertEqual(len(run['patch']['edits']),1)
        for wire in sent[:3]:
            text=json.dumps(wire)
            for forbidden in ('A_REFERENCE_SENTINEL','DO_NOT_SEND_METADATA','DO_NOT_SEND_PATH','scores'):
                self.assertNotIn(forbidden,text)

    def test_source_is_reported_when_valid_schema_opinion_has_no_facets(self):
        invalid=copy.deepcopy(B)
        invalid['opinions'][0]['facets']=[]
        run,sent=self.execute([reply(invalid)])
        self.assertEqual(len(sent),1)
        self.assertEqual(run['patch']['edits'],[])
        self.assertTrue(any(item.get('section_id') and 'output rejected' in item['reason'] for item in run['unprocessed']))
        self.assertEqual(run['format_repair_count'],0)

    def test_replay_and_local_do_not_perform_format_repairs(self):
        from reviewproto.attention_candidates import ReplayProvider, LocalProvider
        for local in (False,True):
            class FakeLocal(LocalProvider):
                def complete(self,request):
                    return {'choices':[{'message':{'content':'{'},'finish_reason':'stop'}],'usage':USAGE}
            with self.subTest(local=local), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
                ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'单位已经说明。'}],
                          'a_reference':{'version':'none','items':[]}})
                provider=FakeLocal() if local else ReplayProvider([{'choices':[{'message':{'content':'{'},'finish_reason':'stop'}],'usage':USAGE}])
                run=generate(ws,'old-path',provider)
                self.assertEqual(len(run['calls']),1)
                self.assertEqual(run['format_repair_count'],0)

    def test_cli_and_preview_explain_repair_and_keep_error_status(self):
        from reviewproto.attention_candidate_render import render_candidate_preview
        from reviewproto.cli import main
        from contextlib import redirect_stdout
        run,_=self.execute([reply('{'),reply(B),reply({'function':'实质评价'})])
        page=render_candidate_preview(run)
        self.assertIn('发生格式修复 1 次',page)
        self.assertIn('首次失败',page)
        with tempfile.TemporaryDirectory() as tmp, patch('reviewproto.attention_candidates.generate',return_value=run):
            stream=io.StringIO()
            with redirect_stdout(stream):
                code=main(['attention-generate','--workspace',tmp,'--run-id','cli','--provider','deepseek'])
            self.assertEqual(code,2)
            self.assertIn('FORMAT_REPAIR requests=1 original_failures_preserved=yes',stream.getvalue())
