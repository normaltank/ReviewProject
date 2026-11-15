"""Record-batched experiment through public generation and saving seams."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate, preview, accept, ReplayProvider
from reviewproto.attention_api_provider import DeepSeekProvider
from reviewproto.core import ReviewError


def facet(ref, focus, passages, **extra):
    return dict(ref=ref, focus=focus, state='建议', boilerplate=False,
                evidence=[{'section':'s1','passage':p} for p in passages],
                qualifiers={}, themes=[], **extra)


def b_response(facets):
    return {'opinions':[{'summary':'合成关注','facets':facets}], 'relations':[], 'unprocessed':[]}


def replay(responses):
    provider=ReplayProvider(responses)
    provider.config['context_tokens']=1000000
    return provider


def pair(a_text, rows):
    return {'a_text':a_text,'comparisons':{key:{'b_text':literal,'kind':kind,'reason':'合成对象依据'}
            for key,literal,kind in rows}}


def matrix():
    return {'facets':{
        'f1':{'comparisons':{
            'a1':pair('呈现单位',[('b1','请说明单位。','explicit'),('b2','请另存附件。','unrelated')]),
            'a2':pair('说明符号',[('b1','请说明单位。','partial'),('b2','请另存附件。','unrelated')])}},
        'f2':{'comparisons':{
            'a1':pair('呈现单位',[('b1','请解释符号。','undetermined')]),
            'a2':pair('说明符号',[('b1','请解释符号。','related')])}}}}


class RemoteReplay(ReplayProvider):
    """Injected external boundary; validates real API drafts without network."""
    mode='remote_api'

    def __init__(self,responses):
        super().__init__(responses)
        self.config.update(provider='deepseek-api/1',model='deepseek-flash',context_tokens=1000000,max_tokens=8192)


def reply(value,finish='stop',usage=True):
    result={'choices':[{'message':{'content':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)},'finish_reason':finish}]}
    if usage: result['usage']={'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}
    return result


class RecordBatched(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws=AttentionWorkspace(Path(self.temp.name)/'pack')
        self.addCleanup(self.ws.close)

    def build(self, text='请说明单位。', items=None, records=None):
        return self.ws.build({'schema':'attention-input/1',
            'records':records or [{'anchor':'IDENTITY_SENTINEL','visibility':'author_visible',
                'text':text,'scores':[{'label':'SCORE_SENTINEL','raw_value':'12345'}]}],
            'a_reference':{'version':'synthetic-v1','items':items or []}})

    def test_b_only_one_request_keeps_formal_files_and_saves_through_existing_route(self):
        self.build()
        formal={p.name:p.read_bytes() for p in self.ws.path.iterdir() if p.is_file()}
        provider=ReplayProvider([b_response([facet('f1','说明单位',['p1'])])])
        provider.config['context_tokens']=200000
        run=generate(self.ws,'record',provider,analysis_strategy='record-batched')
        self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
        self.assertEqual(run['request_count'],1)
        self.assertEqual(run['analysis_strategy'],'record-batched')
        self.assertEqual(run['intermediate_protocol'],'attention-record-semantic/1')
        self.assertIn('record_semantic_adapter_hash',run)
        self.assertEqual(len(run['source_scopes']),1)
        self.assertEqual(self.ws.state()['revision'],0)
        for name,before in formal.items(): self.assertEqual((self.ws.path/name).read_bytes(),before,name)
        draft=preview(self.ws,'record')
        f=draft['patch']['edits'][0]['facets'][0]
        self.assertEqual(f['evidence'][0]['quote'],'请说明单位。')
        self.assertEqual(f['expression']['function'],'建议')
        self.assertEqual(f.get('outside',[]),[])
        self.assertEqual(accept(self.ws,'record',actor='editor',reason='核对')['revision'],1)
        self.assertEqual(accept(self.ws,'record',actor='editor',reason='重复')['revision'],1)

    def multi(self):
        self.build('请说明单位。请另存附件。请解释符号。',[
            {'id':'units','text':'呈现单位','locator':'PATH_SENTINEL'},
            {'id':'symbols','text':'说明符号','locator':'PATH_SENTINEL'}])
        return b_response([
            facet('f1','单位及附件',['p1','p2'],ranges=[
                {'focus':'单位','evidence':[{'section':'s1','passage':'p1'}]},
                {'focus':'附件','evidence':[{'section':'s1','passage':'p2'}]}]),
            facet('f2','符号',['p3'])])

    def test_full_matrix_retains_multiple_links_local_outside_and_uncertainty_in_two_calls(self):
        b=self.multi()
        run=generate(self.ws,'matrix',replay([b,matrix()]),analysis_strategy='record-batched')
        self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
        self.assertEqual(run['request_count'],2)
        self.assertEqual([c['stage'] for c in run['calls']],['b_analysis','a_mapping'])
        wire=json.dumps(run['calls'][0]['request'],ensure_ascii=False)
        for forbidden in ('呈现单位','说明符号','SCORE_SENTINEL','12345','PATH_SENTINEL','IDENTITY_SENTINEL',
                          'record_id','source_id','a_reference','不分类表达功能'):
            self.assertNotIn(forbidden,wire)
        first,second=run['patch']['edits'][0]['facets']
        self.assertEqual([(p['a_item_id'],p['kind']) for p in first['a_links']],[('units','explicit'),('symbols','partial')])
        self.assertEqual(len(first['outside']),1)
        self.assertEqual(first['outside'][0]['scope'],'附件：请另存附件。')
        self.assertEqual([(p['a_item_id'],p['kind']) for p in second['a_links']],[('units','undetermined'),('symbols','related')])
        self.assertEqual(second['outside'],[])
        schema=run['calls'][1]['request']['response_format']['json_schema']['schema']
        rows=schema['properties']['facets']['properties']
        self.assertEqual(set(rows),{'f1','f2'})
        p=rows['f1']['properties']['comparisons']['properties']
        self.assertEqual(set(p),{'a1','a2'})
        self.assertEqual(p['a1']['properties']['a_text']['enum'],['呈现单位'])
        self.assertEqual(p['a1']['properties']['comparisons']['properties']['b2']['properties']['b_text']['enum'],['请另存附件。'])
        self.assertEqual(len(run['source_scopes'][first['facet_id']]),2)
        self.assertEqual(accept(self.ws,'matrix',actor='editor',reason='核对')['revision'],1)

    def test_duplicate_b_reference_cannot_replace_first_accepted_frozen_range(self):
        self.build('请说明单位。请另存附件。',[{'id':'unit','text':'呈现单位','locator':'x'}])
        b=b_response([facet('f1','单位',['p1']),facet('f1','附件',['p2'])])
        a={'facets':{'f1':{'comparisons':{'a1':pair('呈现单位',[('b1','请说明单位。','explicit')])}}}}
        run=generate(self.ws,'duplicate',replay([b,a]),analysis_strategy='record-batched')
        self.assertEqual(run['status'],'partial')
        first=run['patch']['edits'][0]['facets'][0]
        self.assertEqual(run['source_scopes'][first['facet_id']][0]['text'],'请说明单位。')
        self.assertEqual(len(first['a_links']),1)

    def test_complete_record_matrix_is_required_before_any_outside_is_inferred(self):
        b=self.multi()
        for case in ('missing_a','missing_scope','missing_facet','unknown_a','bad_a','bad_b','rewrite','unknown_kind'):
            with self.subTest(case=case):
                a=matrix()
                if case=='missing_a': del a['facets']['f1']['comparisons']['a2']
                if case=='missing_scope': del a['facets']['f1']['comparisons']['a1']['comparisons']['b2']
                if case=='missing_facet': del a['facets']['f2']
                if case=='unknown_a': a['facets']['f1']['comparisons']['unknown']=copy.deepcopy(a['facets']['f1']['comparisons']['a1'])
                if case=='bad_a': a['facets']['f1']['comparisons']['a1']['a_text']='篡改A'
                if case=='bad_b': a['facets']['f1']['comparisons']['a1']['comparisons']['b1']['b_text']='篡改B'
                if case=='rewrite': a['facets']['f1']['focus']='换掉B对象'
                if case=='unknown_kind': a['facets']['f1']['comparisons']['a1']['comparisons']['b1']['kind']='outside'
                run=generate(self.ws,case,replay([b,a]),analysis_strategy='record-batched')
                self.assertEqual(run['status'],'partial')
                self.assertEqual(run['request_count'],2)
                self.assertEqual(len(run['patch']['edits'][0]['facets']),2)
                for f in run['patch']['edits'][0]['facets']:
                    self.assertEqual(f.get('a_links',[]),[])
                    self.assertEqual(f.get('outside',[]),[])
                self.assertEqual(len([p for p in run['unprocessed'] if 'facet_id' in p]),2)

    def test_all_b_precedes_a_and_complete_eighteen_item_reference_is_compared(self):
        items=[{'id':'item'+str(i),'text':'合成关注'+str(i),'locator':'x'} for i in range(1,19)]
        self.build(items=items,records=[{'anchor':str(i),'visibility':'author_visible','text':'请说明单位。'} for i in range(2)])
        b=b_response([facet('f1','单位',['p1'])])
        a={'facets':{'f1':{'comparisons':{'a'+str(i):pair('合成关注'+str(i),
            [('b1','请说明单位。','explicit' if i==18 else 'unrelated')]) for i in range(1,19)}}}}
        run=generate(self.ws,'eighteen',replay([b,b,a,a]),analysis_strategy='record-batched')
        self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
        self.assertEqual(run['request_count'],4)
        self.assertEqual([c['stage'] for c in run['calls']],['b_analysis','b_analysis','a_mapping','a_mapping'])
        ids=[]
        for op in run['patch']['edits']:
            f=op['facets'][0];ids.append(f['facet_id'])
            self.assertEqual([p['a_item_id'] for p in f['a_links']],['item18'])
            self.assertEqual(f['outside'],[])
        self.assertEqual(len(set(ids)),2)
        for call in run['calls'][2:]:
            payload=json.loads(call['request']['messages'][1]['content'])
            self.assertEqual(len(payload['reference']),18)

    def test_capacity_rejects_whole_a_matrix_without_truncating_or_fallback(self):
        b=b_response([facet('f1','单位及附件',['p1','p2']),facet('f2','符号',['p3'])])
        # A large complete reference fits storage but not this experiment's input limit.
        self.ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
            'text':'请说明单位。请另存附件。请解释符号。'}],
            'a_reference':{'version':'large','items':[{'id':'large','text':'长参照'*2000,'locator':'x'}]}})
        run=generate(self.ws,'capacity',replay([b]),context_chars=2000,analysis_strategy='record-batched')
        self.assertEqual(run['status'],'partial',run['errors'])
        self.assertEqual(run['request_count'],1)
        self.assertEqual(len(run['calls']),2)
        self.assertEqual(run['calls'][1]['error'],'E_ATTENTION_CAPACITY')
        payload=json.loads(run['calls'][1]['request']['messages'][1]['content'])
        self.assertEqual(payload['reference'][0]['text'],'长参照'*2000)
        self.assertEqual(len(payload['facets']),2)
        self.assertTrue(all(not f.get('outside') for op in run['patch']['edits'] for f in op['facets']))

    def test_one_format_repair_uses_same_schema_and_keeps_failure_partial(self):
        self.build()
        b=b_response([facet('f1','单位',['p1'])])
        run=generate(self.ws,'repair',RemoteReplay([reply('{"opinions":['),reply(b)]),analysis_strategy='record-batched')
        self.assertEqual(run['status'],'partial',run['errors'])
        self.assertEqual(run['request_count'],2)
        self.assertEqual(run['format_repair_count'],1)
        self.assertEqual(len(run['patch']['edits']),1)
        first,repair=run['calls']
        self.assertEqual(first['schema_hash'],repair['schema_hash'])
        self.assertEqual(first['request']['messages'][1],repair['request']['messages'][1])
        self.assertEqual(repair['purpose'],'format_repair')
        wire=json.dumps(repair['request'],ensure_ascii=False)
        for secret in ('SCORE_SENTINEL','12345','IDENTITY_SENTINEL'): self.assertNotIn(secret,wire)

    def test_official_provider_prepares_two_complete_wire_requests_without_external_io(self):
        b=self.multi();sent=[];responses=iter([reply(b),reply(matrix())])
        def open_fake(request,**kwargs):
            sent.append(json.loads(request.data))
            stream=io.BytesIO(json.dumps(next(responses),ensure_ascii=False).encode())
            stream.status=200
            return stream
        with patch('reviewproto.attention_api_provider.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=open_fake
            run=generate(self.ws,'wire',DeepSeekProvider(credential_loader=lambda:'SYNTHETIC_KEY'),analysis_strategy='record-batched')
        self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
        self.assertEqual(len(sent),2)
        self.assertEqual(run['request_count'],2)
        for wire,call in zip(sent,run['calls']):
            self.assertEqual(wire,call['request'])
            self.assertEqual(wire['response_format'],{'type':'json_object'})
            self.assertEqual(wire['model'],'deepseek-flash')
            self.assertEqual(wire['max_tokens'],32768)
        b_wire=json.dumps(sent[0],ensure_ascii=False)
        for forbidden in ('呈现单位','说明符号','SCORE_SENTINEL','PATH_SENTINEL','IDENTITY_SENTINEL','SYNTHETIC_KEY'):
            self.assertNotIn(forbidden,b_wire)
        self.assertNotIn('SYNTHETIC_KEY',json.dumps(run))

    def test_a_schema_format_repair_keeps_valid_b_and_returns_full_positions(self):
        b=self.multi();bad=matrix();del bad['facets']['f2']
        run=generate(self.ws,'a-repair',RemoteReplay([reply(b),reply(bad),reply(matrix())]),analysis_strategy='record-batched')
        self.assertEqual(run['status'],'partial')
        self.assertEqual(run['request_count'],3)
        self.assertEqual(run['format_repair_count'],1)
        self.assertEqual(len(run['patch']['edits'][0]['facets'][0]['outside']),1)
        self.assertEqual(len(run['patch']['edits'][0]['facets'][1]['a_links']),2)
        self.assertEqual(run['calls'][1]['schema_hash'],run['calls'][2]['schema_hash'])
        self.assertEqual(run['calls'][1]['request']['messages'][1],run['calls'][2]['request']['messages'][1])

    def test_bad_a_repair_truncation_or_provider_failure_never_implies_outside(self):
        b=self.multi()
        missing=matrix();del missing['facets']['f2']
        cases=[('bad-repair',[reply(b),reply(missing),reply(missing)],3,1),
               ('truncated',[reply(b),reply(matrix(),finish='length')],2,0),
               ('provider-failure',[reply(b),RuntimeError('synthetic transport failure')],2,0)]
        for name,responses,requests,repairs in cases:
            with self.subTest(name=name):
                run=generate(self.ws,name,RemoteReplay(responses),analysis_strategy='record-batched')
                self.assertEqual(run['status'],'partial',run['errors'])
                self.assertEqual(run['request_count'],requests)
                self.assertEqual(run['format_repair_count'],repairs)
                self.assertEqual(len(run['patch']['edits'][0]['facets']),2)
                self.assertTrue(all(not f.get('outside') and not f.get('a_links') for op in run['patch']['edits'] for f in op['facets']))

    def test_correction_repeat_accept_and_recover_keep_saved_revision(self):
        self.build()
        run=generate(self.ws,'save',replay([b_response([facet('f1','单位',['p1'])])]),analysis_strategy='record-batched')
        saved=accept(self.ws,'save',actor='editor',reason='核对')
        op=copy.deepcopy(saved['opinions'][0])
        for key in ('superseded_by','evidence','facet_id','themes','a_links','outside','expression','qualifiers'): op.pop(key,None)
        op['interpretation']='人工纠正保留';op['status']='confirmed'
        patch=copy.deepcopy(run['patch']);patch.update(base_revision=1,actor='editor',reason='纠正',edits=[op])
        self.ws.apply(patch)
        self.assertEqual(accept(self.ws,'save',actor='other',reason='重复')['revision'],2)
        html=self.ws.path/'attention.html';html.unlink();html.mkdir()
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_OUTPUT_RECOVER'): self.ws.recover()
        self.assertEqual(self.ws.state()['revision'],2)
        html.rmdir();self.ws.recover()
        reopened=AttentionWorkspace(self.ws.path)
        try:
            self.assertEqual(reopened.state()['opinions'][0]['interpretation'],'人工纠正保留')
            self.assertEqual(accept(reopened,'save',actor='other',reason='重开')['revision'],2)
            self.assertEqual(preview(reopened,'save')['patch']['edits'][0]['facets'][0]['facet_id'],run['patch']['edits'][0]['facets'][0]['facet_id'])
        finally: reopened.close()

    def test_source_bound_conditions_negation_and_relation_survive_record_acceptance(self):
        original='若材料尚未齐备，可先缩小结论范围，不要求追加实验。'
        self.build(original)
        f=facet('f1','条件下缩小范围',['p1','p2','p3'])
        f['qualifiers']={'conditions':'若材料尚未齐备，','actions':'可先缩小结论范围，','negation':'不要求追加实验。'}
        b=b_response([f]);b['relations']=[{'type':'条件约束',
            'endpoints':[{'facet':'f1','role':'条件'},{'facet':'f1','role':'动作'}],
            'direction':'条件作用于动作','scope':'材料不足时缩小范围',
            'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'}],
            'reading':'按条件缩小范围','ambiguity':''}]
        run=generate(self.ws,'conditions',replay([b]),analysis_strategy='record-batched')
        self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
        self.assertEqual(run['request_count'],1)
        saved=accept(self.ws,'conditions',actor='editor',reason='核对')
        f=saved['opinions'][0]['facets'][0]
        self.assertIn(original,f['interpretation'])
        self.assertEqual(f['qualifiers']['negation'],'不要求追加实验。')
        self.assertEqual(f['qualifiers']['conditions'],'若材料尚未齐备，')
        self.assertEqual(len(saved['relations']),1)
        self.assertEqual(saved['relations'][0]['endpoints'][0]['facet_id'],f['facet_id'])
        self.assertEqual(len(run['source_scopes'][f['facet_id']]),1)

    def test_ranges_cannot_drop_selected_evidence_and_hallucinated_quotes_are_rejected(self):
        self.build('请说明单位。请另存附件。')
        cases=[facet('f1','单位及附件',['p1','p2'],ranges=[{'focus':'单位','evidence':[{'section':'s1','passage':'p1'}]}]),
               facet('f1','单位',['p1'],ranges=[{'focus':'附件','evidence':[{'section':'s1','passage':'p2'}]}]),
               dict(facet('f1','单位',['p1']),evidence=[{'section':'s1','quote':'请重写单位。','start':0,'end':6}])]
        for index,f in enumerate(cases):
            with self.subTest(index=index):
                run=generate(self.ws,'bad-source'+str(index),replay([b_response([f])]),analysis_strategy='record-batched')
                self.assertEqual(run['status'],'failed')
                self.assertEqual(run['request_count'],1)
                self.assertEqual(run['patch']['edits'],[])
                self.assertTrue(run['unprocessed'])
                self.assertTrue(run['rejected'])

    def test_strategy_is_explicit_bounded_and_unsupported_providers_fail_before_a_run(self):
        self.build()
        for strategy in ('unknown',None,[],{}):
            with self.subTest(strategy=strategy), self.assertRaisesRegex(ReviewError,'E_ATTENTION_ANALYSIS_STRATEGY'):
                generate(self.ws,'invalid',replay([]),analysis_strategy=strategy)
        provider=replay([]);provider.mode='local_model'
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_PROVIDER'):
            generate(self.ws,'invalid',provider,analysis_strategy='record-batched')
        self.assertFalse((self.ws.path/'candidate-runs/invalid').exists())


if __name__=='__main__': unittest.main()
