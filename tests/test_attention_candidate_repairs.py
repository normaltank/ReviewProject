"""Public candidate regressions for the centralized spec repair."""
import tempfile
import unittest
import json
from contextlib import closing
from pathlib import Path
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate, accept, ReplayProvider


class CandidateRepairs(unittest.TestCase):
    def test_unknown_or_failed_scoped_a_row_never_becomes_outside(self):
        for uncertain in (True,False):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
                ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'说明单位。'}],
                    'a_reference':{'version':'v','items':[{'id':'first','text':'图示解释','locator':'x'},
                        {'id':'second','text':'资料存放','locator':'y'}]}})
                b={'opinions':[{'summary':'单位','facets':[{'ref':'f','focus':'单位',
                    'evidence':[{'section':'s1','passage':'p1'}],'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
                first={'a_text':'图示解释','comparisons':{'b1':{'b_text':'说明单位。',
                    'kind':'undetermined' if uncertain else 'unrelated','reason':'解释范围尚未确定' if uncertain else '对象不同'}}}
                second=({'a_text':'资料存放','comparisons':{'b1':{'b_text':'说明单位。','kind':'unrelated','reason':'对象不同'}}}
                    if uncertain else RuntimeError('explicit synthetic transport failure'))
                run=generate(ws,'unclear',ReplayProvider([b,{'function':'修改建议'},first,second]))
                f=run['patch']['edits'][0]['facets'][0]
                self.assertEqual(f['outside'],[])
                self.assertEqual([a['kind'] for a in f['a_links']],['undetermined'] if uncertain else [])
                self.assertEqual(run['status'],'complete' if uncertain else 'partial')
                if not uncertain: self.assertTrue(run['unprocessed'])

    def test_focused_function_and_all_a_scope_rows_derive_mixed_positions(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
                'text':'图例已清楚，请增加检索提示。'}], 'a_reference':{'version':'v-scopes','items':[
                    {'id':'unrelated-new','text':'材料保管地点','locator':'x'},
                    {'id':'labels-new','text':'图例是否可读','locator':'y'}]}})
            b={'opinions':[{'summary':'图例与检索','facets':[{'ref':'f','focus':'图例',
                'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'}],
                'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            class Provider(ReplayProvider):
                def complete(self,request):
                    payload=json.loads(request['messages'][1]['content'])
                    if 'sections' in payload: return super().complete(request)
                    if 'selected' in payload:
                        response={'function':'实质评价'}
                    else:
                        item=payload['a_item']['text']
                        response={'a_text':item,'comparisons':{scope['id']:{'b_text':scope['text'],
                            'kind':'explicit' if item=='图例是否可读' and scope['id']=='b1' else 'unrelated',
                            'reason':'仅图例与可读性相交' if scope['id']=='b1' else '两项A都不谈检索提示'} for scope in payload['scopes']}}
                    return ReplayProvider([response]).complete(request)
            run=generate(ws,'fixed-rows',Provider([b]))
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            f=accept(ws,'fixed-rows',actor='editor',reason='inspect')['opinions'][0]['facets'][0]
            self.assertEqual(f['kind'],'content');self.assertEqual(f['expression']['function'],'评价')
            self.assertEqual([(a['a_item_id'],a['scope']) for a in f['a_links']],[('labels-new','图例已清楚，')])
            self.assertEqual([o['scope'] for o in f['outside']],['请增加检索提示。'])
            self.assertEqual(run['request_count'],4)

    def test_eighteen_pairwise_a_items_fit_and_preserve_complete_reference(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            items=[{'id':'fresh-key-'+str(i),'text':'记录来源第'+str(i)+'项的保存位置和适用时段。','locator':'synthetic'} for i in range(18)]
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
                'text':'标明示意图方向。'}], 'a_reference':{'version':'new-eighteen','items':items}})
            b={'opinions':[{'summary':'图向','facets':[{'ref':'f','focus':'示意图方向',
                'evidence':[{'section':'s1','passage':'p1'}],
                'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            references=[]
            class Provider(ReplayProvider):
                def complete(self,request):
                    payload=json.loads(request['messages'][1]['content'])
                    if 'sections' in payload: return super().complete(request)
                    if 'selected' in payload:
                        return ReplayProvider([{'function':'修改建议'}]).complete(request)
                    references.append(payload['a_item']['text'])
                    response={'a_text':payload['a_item']['text'],'comparisons':{
                        s['id']:{'b_text':s['text'],'kind':'unrelated','reason':'保存位置与图中方向不同'} for s in payload['scopes']}}
                    return ReplayProvider([response]).complete(request)
            run=generate(ws,'eighteen-pairs',Provider([b]))
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            self.assertEqual(references,[i['text'] for i in items])
            self.assertEqual(run['request_count'],20)
            self.assertEqual(run['unprocessed'],[])
            self.assertEqual(len(run['patch']['edits'][0]['facets'][0]['outside']),1)

    def test_changed_a_text_is_rejected_without_inventing_outside(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
                'text':'若没有旧档，只需注明版本；不要求重建。'}], 'a_reference':{'version':'v','items':[
                    {'id':'unseen-key','text':'说明版本来历','locator':'x'}]}})
            b={'opinions':[{'summary':'版本','facets':[{'ref':'f','focus':'注明版本','state':'建议',
                'boilerplate':False,'evidence':[{'section':'s1','passage':'p2'}],
                'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            bad={'a_text':'核算原始数据','positions':[{'kind':'related','scope':'注明版本','reason':'错误A条目'}],'reason':'另一条内容'}
            run=generate(ws,'wrong-text',ReplayProvider([b,bad]))
            self.assertEqual(run['status'],'partial')
            f=run['patch']['edits'][0]['facets'][0]
            self.assertIn('若没有旧档，只需注明版本；',f['interpretation'])
            self.assertEqual(f['a_links'],[]);self.assertEqual(f['outside'],[])
            self.assertIn('E_ATTENTION_A_TEXT',str(run['rejected']))
            self.assertEqual(run['request_count'],2)
            self.assertTrue(run['unprocessed'])

    def test_pairwise_a_binding_and_same_facet_partial_outside_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
                'text':'图例已清楚，请附检索提示和保存时间。'}], 'a_reference':{'version':'r-new','items':[
                    {'id':'totally-different-first','text':'检验药品质量','locator':'x'},
                    {'id':'new-label-id','text':'图例是否可读','locator':'y'}]}})
            b={'opinions':[{'summary':'呈现和提示','facets':[{'ref':'x','focus':'图例',
                'state':'建议','boilerplate':False,'evidence':[{'section':'s1','quote':'图例已清楚，请附检索提示和保存时间。'}],
                'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            class Provider(ReplayProvider):
                def complete(self, request):
                    payload=json.loads(request['messages'][1]['content'])
                    if 'sections' in payload: return super().complete(request)
                    if 'a_item' in payload:
                        item=payload['a_item']
                        return ReplayProvider([{'a_text':item['text'],'positions':([] if item['text']=='检验药品质量' else [
                            {'kind':'explicit','scope':'图例已清楚','reason':'具体图例可读判断'}]),
                            'reason':'仅比较本条原文'}]).complete(request)
                    self_test.assertEqual(len(payload['reference']),2)
                    return ReplayProvider([{'outside':[{'scope':'检索提示','reason':'本版两项均没有检索提示'}],
                        'undetermined':[{'scope':'保存时间','reason':'保存对象未明确，不能确定是图例还是资料'}]}]).complete(request)
            self_test=self
            run=generate(ws,'positions',Provider([b]))
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            saved=accept(ws,'positions',actor='editor',reason='check')
            facet=saved['opinions'][0]['facets'][0]
            self.assertEqual([(l['a_item_id'],l['kind']) for l in facet['a_links']],
                             [('new-label-id','explicit'),(None,'undetermined')])
            self.assertEqual(facet['outside'][0]['scope'],'检索提示')
            self.assertEqual(run['request_count'],4)

    def test_source_bound_unknown_alternatives_and_disposition_survive_accept(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
                'text':'感谢修改，建议发表。缺口表示未测还是测量失败，目前不清楚；不要求重新测量。'}],
                'a_reference':{'version':'none','items':[]}})
            b={'opinions':[{'summary':'流程及缺口含义','facets':[
                {'ref':'d','focus':'建议发表','state':'稿件录用或退修决定','boilerplate':False,
                 'evidence':[{'section':'s1','quote':'建议发表。'}],'qualifiers':{},'themes':[]},
                {'ref':'u','focus':'缺口','state':'未知','boilerplate':False,
                 'evidence':[{'section':'s1','quote':'缺口表示未测还是测量失败，目前不清楚；不要求重新测量。'}],
                 'qualifiers':{'alternatives':['未测','测量失败'],'negation':'不要求重新测量'},'themes':[]}]}],
                'relations':[],'unprocessed':[]}
            run=generate(ws,'meaning',ReplayProvider([b]))
            self.assertEqual(run['status'],'complete',run['rejected'])
            saved=accept(ws,'meaning',actor='editor',reason='inspect')
            facets=saved['opinions'][0]['facets']
            self.assertEqual(facets[0]['kind'],'disposition')
            self.assertIn('未测还是测量失败，目前不清楚',facets[1]['interpretation'])
            self.assertIn('不要求重新测量',facets[1]['interpretation'])
            self.assertEqual(facets[1]['qualifiers']['alternatives'],['未测','测量失败'])

    def test_internal_relation_can_use_one_facet_or_two_roles_on_same_facet(self):
        for roles in (['备用动作'], ['条件', '动作']):
            with self.subTest(roles=roles), tempfile.TemporaryDirectory() as tmp:
                with closing(AttentionWorkspace(Path(tmp) / 'pack')) as workspace:
                    workspace.build({'schema':'attention-input/1', 'records':[{'anchor':'s',
                        'text':'如有记录，可补充时间。', 'visibility':'author_visible'}],
                        'a_reference':{'version':'none','items':[]}})
                    b={'opinions':[{'summary':'有条件补充时间','facets':[{'ref':'f',
                        'reading':'如有记录才可补充时间','kind':'content','expression':'建议',
                        'boilerplate':False,'evidence':[{'section':'s1','passage':'p1'}],
                        'qualifiers':{},'themes':[]}]}], 'relations':[{'type':'conditional',
                        'endpoints':[{'facet':'f','role':role} for role in roles],
                        'direction':'条件约束动作','scope':'补充时间','evidence':[{'section':'s1','passage':'p1'}],
                        'reading':'仅在有记录时可补充','ambiguity':''}], 'unprocessed':[]}
                    run=generate(workspace,'relation',ReplayProvider([b]))
                    self.assertEqual(run['status'],'complete',run['rejected'])
                    saved=accept(workspace,'relation',actor='editor',reason='check')
                    self.assertEqual(len(saved['relations']),1)
                    self.assertEqual(len(saved['relations'][0]['endpoints']),len(roles))
