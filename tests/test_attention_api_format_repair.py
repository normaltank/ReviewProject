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
from reviewproto.local_io import encoded

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
            saved=json.loads((ws.path/'candidate-runs/format/run.json').read_text(encoding='utf-8'))
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

    def test_json_decoder_diagnostic_is_audited_and_sent_to_only_repair(self):
        # Extra closing brace is on line2/column1 at Python codepoint3.
        invalid='{}\n}'
        run,sent=self.execute([reply(invalid),reply(B),reply({'function':'实质评价'})])
        diagnostic={'kind':'json_decode','message':'Extra data','line':2,'column':1,'position':3}
        self.assertEqual(run['calls'][0]['format_diagnostic'],diagnostic)
        repair_text=sent[1]['messages'][-1]['content']
        self.assertIn(json.dumps(diagnostic,ensure_ascii=False,separators=(',',':')),repair_text)
        self.assertEqual(sent[1]['messages'][2],{'role':'assistant','content':invalid})
        self.assertEqual(sent[0]['messages'][:2],sent[1]['messages'][:2])
        self.assertEqual(sent[0]['max_tokens'],sent[1]['max_tokens'])
        self.assertEqual(run['calls'][1]['request_hash'],digest(encoded(sent[1])))
        self.assertEqual(run['request_count'],3)
        self.assertEqual(run['format_repair_count'],1)
        self.assertEqual(run['status'],'partial')

    def test_schema_repair_diagnostic_has_safe_paths_not_raw_validation_values(self):
        invalid=copy.deepcopy(B);invalid['opinions']='PRIVATE_VALIDATION_VALUE'
        run,sent=self.execute([reply(invalid),reply(B),reply({'function':'实质评价'})])
        diagnostic=run['calls'][0]['format_diagnostic']
        self.assertEqual(diagnostic['kind'],'json_schema')
        self.assertEqual(diagnostic['validator'],'type')
        self.assertEqual(diagnostic['data_path'],['opinions'])
        self.assertEqual(diagnostic['schema_path'],['properties','opinions','type'])
        self.assertIn('PRIVATE_VALIDATION_VALUE',run['calls'][0]['schema_validation']['message'])
        repair_instruction=sent[1]['messages'][-1]['content']
        self.assertIn(json.dumps(diagnostic,ensure_ascii=False,separators=(',',':')),repair_instruction)
        self.assertNotIn('PRIVATE_VALIDATION_VALUE',repair_instruction)
        for forbidden in ('A_REFERENCE_SENTINEL','DO_NOT_SEND_PATH','DO_NOT_SEND_METADATA','FAKE-KEY'):
            self.assertNotIn(forbidden,repair_instruction)
        self.assertIn('PRIVATE_VALIDATION_VALUE',sent[1]['messages'][2]['content'])
        self.assertEqual(run['calls'][0]['status'],'failed')

    def test_nested_opinion_relations_diagnostic_names_wrong_and_allowed_fields(self):
        invalid=copy.deepcopy(B)
        invalid['opinions'][0]['relations']=[{'business_value':'DO_NOT_ECHO_VALUE'}]
        run,sent=self.execute([reply(invalid),reply(B),reply({'function':'实质评价'})])
        diagnostic=run['calls'][0]['format_diagnostic']
        issue=next(e for e in diagnostic['errors'] if e['validator']=='additionalProperties')
        self.assertEqual(issue['data_path'],['opinions',0])
        self.assertEqual(issue['unexpected_fields'],['relations'])
        self.assertEqual(set(issue['allowed_fields']),{'summary','facets'})
        instruction=sent[1]['messages'][-1]['content']
        self.assertNotIn('DO_NOT_ECHO_VALUE',instruction)
        self.assertIn(json.dumps(diagnostic,ensure_ascii=False,separators=(',',':')),instruction)
        self.assertEqual(sent[0]['messages'][:2],sent[1]['messages'][:2])
        self.assertEqual(sent[0]['max_tokens'],sent[1]['max_tokens'])
        self.assertEqual(run['calls'][1]['request_hash'],digest(encoded(sent[1])))
        self.assertEqual(run['request_count'],3)
        self.assertEqual(run['format_repair_count'],1)
        self.assertEqual(run['status'],'partial')

    def test_schema_diagnostic_reports_missing_fields_and_types_without_values(self):
        invalid=copy.deepcopy(B)
        del invalid['opinions'][0]['summary']
        facet=invalid['opinions'][0]['facets'][0]
        del facet['focus']
        facet['themes']='PRIVATE_TYPE_VALUE'
        invalid['unprocessed']='PRIVATE_OTHER_VALUE'
        run,sent=self.execute([reply(invalid),reply(B),reply({'function':'实质评价'})])
        errors=run['calls'][0]['format_diagnostic']['errors']
        missing={tuple(e['data_path']):e['missing_fields'] for e in errors if e['validator']=='required'}
        self.assertEqual(missing[('opinions',0)],['summary'])
        self.assertEqual(missing[('opinions',0,'facets',0)],['focus'])
        types={tuple(e['data_path']):(e['expected_type'],e['actual_type']) for e in errors if e['validator']=='type'}
        self.assertEqual(types[('opinions',0,'facets',0,'themes')],('array','string'))
        self.assertEqual(types[('unprocessed',)],('array','string'))
        for value in ('PRIVATE_TYPE_VALUE','PRIVATE_OTHER_VALUE','FAKE-KEY','DO_NOT_SEND_PATH'):
            self.assertNotIn(value,sent[1]['messages'][-1]['content'])
        self.assertIn('PRIVATE_TYPE_VALUE',sent[1]['messages'][2]['content'])

    def test_schema_diagnostic_collection_is_bounded(self):
        invalid={'opinions':[{'facets':[]} for _ in range(30)],'relations':[],'unprocessed':[]}
        run,_=self.execute([reply(invalid),reply(B),reply({'function':'实质评价'})])
        diagnostic=run['calls'][0]['format_diagnostic']
        self.assertLessEqual(len(diagnostic['errors']),16)
        self.assertTrue(diagnostic['truncated'])
        self.assertEqual(run['request_count'],3)

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
