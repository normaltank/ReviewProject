"""Public candidate regressions for the centralized spec repair."""
import tempfile
import unittest
import json
from contextlib import closing
from pathlib import Path
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate, accept, ReplayProvider


class CandidateRepairs(unittest.TestCase):
    def test_focus_binding_never_repairs_words_or_literal_evidence(self):
        cases=[('不要求追加实验。','不希望追加实验',[{'section':'s1','passage':'p1'}],'E_ATTENTION_FOCUS_SCOPE'),
               ('“入口清楚”说的是桌面版。','入口清楚',[{'section':'s1','quote':'入口清楚说的是桌面版。','start':0,'end':13}],'E_ATTENTION_QUOTE')]
        for original,focus,ev,code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
                ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':original}],
                          'a_reference':{'version':'none','items':[]}})
                b={'opinions':[{'summary':'来源','facets':[{'ref':'f1','focus':focus,'evidence':ev,'qualifiers':{},'themes':[]}]}],
                    'relations':[],'unprocessed':[]}
                run=generate(ws,'strict',ReplayProvider([b]))
                self.assertEqual(run['status'],'failed');self.assertEqual(run['patch']['edits'],[])
                self.assertIn(code,str(run['rejected']))

    def test_quote_normalized_label_requires_unique_source_correspondence(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
                'text':'“入口清楚”说的是桌面版。“入口清楚”说的是桌面版。'}],'a_reference':{'version':'none','items':[]}})
            b={'opinions':[{'summary':'重复来源','facets':[{'ref':'f1','focus':'入口清楚说的是桌面版',
                'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'}],'qualifiers':{},'themes':[]}]}],
                'relations':[],'unprocessed':[]}
            run=generate(ws,'ambiguous-label',ReplayProvider([b]))
            self.assertEqual(run['status'],'failed')
            self.assertIn('E_ATTENTION_FOCUS_AMBIGUOUS',str(run['rejected']))

    def test_quote_delimiter_focus_binding_keeps_exact_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            original='“入口清楚”说的是桌面版。'
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':original}],
                      'a_reference':{'version':'none','items':[]}})
            b={'opinions':[{'summary':'桌面版判断','facets':[{'ref':'f1','focus':'入口清楚说的是桌面版',
                'evidence':[{'section':'s1','passage':'p1'}],'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            run=generate(ws,'label-quotes',ReplayProvider([b,{'function':'实质评价'}]))
            self.assertEqual(run['status'],'complete',run['rejected'])
            f=run['patch']['edits'][0]['facets'][0]
            self.assertIn('“入口清楚”说的是桌面版',f['interpretation'])
            self.assertEqual(f['evidence'][0]['quote'],original)
            binding=run['focus_bindings'][f['facet_id']]
            self.assertEqual(binding['raw_focus'],'入口清楚说的是桌面版')
            self.assertEqual(binding['source_focus'],'“入口清楚”说的是桌面版')
            self.assertEqual(binding['method'],'quote-delimiter-source-binding/1')

    def test_full_record_context_is_read_only_and_does_not_add_scope_or_other_records(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            original='这一句“必须扩建”是受访者原话；作者只是转述，没有把它当成自己的政策建议。不要据此再写一份扩建方案。'
            state=ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':original},
                {'anchor':'not-selected','visibility':'author_visible','text':'未选择记录不得传入模型。'}],
                'a_reference':{'version':'v','items':[{'id':'voice','text':'区分受访者声音与作者主张','locator':'x'}]}})
            b={'opinions':[{'summary':'方案限制','facets':[{'ref':'f1','focus':'不要据此再写一份扩建方案',
                'evidence':[{'section':'s1','passage':'p4'}],'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            observed=[]
            class Provider(ReplayProvider):
                def complete(self,request):
                    payload=json.loads(request['messages'][1]['content']);observed.append(payload)
                    if 'sections' in payload:return super().complete(request)
                    if 'selected' in payload:return ReplayProvider([{'function':'修改建议'}]).complete(request)
                    response={'a_text':'区分受访者声音与作者主张','comparisons':{'b1':{'b_text':payload['scopes'][0]['text'],
                        'kind':'related','reason':'不得把转述当作作者政策主张并据此要求方案'}}}
                    return ReplayProvider([response]).complete(request)
            run=generate(ws,'context',Provider([b]),record_ids=[state['records'][0]['record_id']])
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            self.assertEqual(observed[1]['context'],[original])
            self.assertEqual(observed[2]['context']['sections'][0]['text'],original)
            self.assertEqual(len(observed[2]['scopes']),1)
            self.assertEqual(observed[2]['scopes'][0]['text'],'不要据此再写一份扩建方案。')
            self.assertNotIn('未选择记录',json.dumps(observed,ensure_ascii=False))
            facet=run['patch']['edits'][0]['facets'][0]
            self.assertIn('受访者原话',facet['interpretation'])
            self.assertEqual(facet['a_links'][0]['a_item_id'],'voice')

    def test_explicit_example_and_negation_keep_their_source_roles(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible',
                'text':'可增加说明，例如列出单位。不要求追加实验。'}],'a_reference':{'version':'none','items':[]}})
            b={'opinions':[{'summary':'说明建议','facets':[{'ref':'f1','focus':'说明',
                'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'},{'section':'s1','passage':'p3'}],
                'qualifiers':{'examples':'例如列出单位。','negation':'不要求追加实验。'},'themes':[]}]}],
                'relations':[],'unprocessed':[]}
            run=generate(ws,'explicit-roles',ReplayProvider([b,{'function':'修改建议'}]))
            self.assertEqual(run['status'],'complete',run['rejected'])
            f=accept(ws,'explicit-roles',actor='editor',reason='check')['opinions'][0]['facets'][0]
            self.assertEqual(f['qualifiers']['examples'],'例如列出单位。')
            self.assertEqual(f['qualifiers']['negation'],'不要求追加实验。')

    def test_obvious_qualifier_role_errors_are_rejected_with_raw_proposal_retained(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            original='若材料尚未齐备，可先缩小结论范围，不要求追加实验。'
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':original}],
                      'a_reference':{'version':'none','items':[]}})
            b={'opinions':[{'summary':'条件建议','facets':[{'ref':'f1','focus':'缩小结论范围',
                'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'},{'section':'s1','passage':'p3'}],
                'qualifiers':{'examples':'不要求追加实验。','negation':'可先缩小结论范围，'},'themes':[]}]}],
                'relations':[],'unprocessed':[]}
            run=generate(ws,'qualifier-role',ReplayProvider([b,{'function':'修改建议'}]))
            self.assertEqual(run['status'],'partial')
            f=run['patch']['edits'][0]['facets'][0]
            self.assertNotIn('examples',f['qualifiers']);self.assertNotIn('negation',f['qualifiers'])
            self.assertIn('不要求追加实验',f['interpretation'])
            self.assertEqual({r['field'] for r in run['rejected']},{'examples','negation'})
            self.assertTrue(all(r['code']=='E_ATTENTION_QUALIFIER_ROLE' for r in run['rejected']))
            self.assertIn('examples',run['calls'][0]['response']['choices'][0]['message']['content'])

    def test_unstated_condition_is_rejected_but_source_supported_relations_survive(self):
        cases=[('感谢修改，建议录用。','条件约束',['条件','动作'],False),
               ('若材料尚未齐备，可先缩小结论范围。','条件约束',['条件','动作'],True),
               ('可保留原说明，或另附解释。','备选',['备选项一','备选项二'],True)]
        for original,kind,roles,supported in cases:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
                ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':original}],
                          'a_reference':{'version':'none','items':[]}})
                raw={'opinions':[{'summary':'来源关系','facets':[{'ref':'f1','focus':original.split('，')[0],
                    'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'}],
                    'qualifiers':{},'themes':[]}]}],'relations':[{'type':kind,
                    'endpoints':[{'facet':'f1','role':role} for role in roles],
                    'direction':'条件或选项作用于后续处理','scope':'当前说明或处理方式',
                    'reading':'按原话保留条件或备选范围','ambiguity':'',
                    'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'}]}],'unprocessed':[]}
                run=generate(ws,'connection',ReplayProvider([raw,{'function':'修改建议'}]))
                if supported:
                    self.assertEqual(run['status'],'complete',run['rejected'])
                    self.assertEqual(len(run['patch']['relations']),1)
                else:
                    self.assertEqual(run['status'],'partial')
                    self.assertEqual(run['patch']['relations'],[])
                    self.assertIn('E_ATTENTION_RELATION_CONNECTION',str(run['rejected']))
                    self.assertIn('条件约束',run['calls'][0]['response']['choices'][0]['message']['content'])
                saved=accept(ws,'connection',actor='editor',reason='check')
                self.assertEqual(len(saved['relations']),int(supported))
                self.assertEqual(len(saved['opinions']),1)

    def test_explicit_ranges_cannot_escape_or_drop_facet_source_group(self):
        for missing in (False,True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
                ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'图例已清楚，保留检索提示。'}],
                    'a_reference':{'version':'v','items':[{'id':'a','text':'图例说明','locator':'x'}]}})
                facet={'ref':'f1','focus':'图例','evidence':[{'section':'s1','passage':'p1'}],
                    'ranges':[{'focus':'检索提示','evidence':[{'section':'s1','passage':'p2'}]}],
                    'qualifiers':{},'themes':[]}
                if missing:
                    facet['evidence'].append({'section':'s1','passage':'p2'})
                    facet['ranges']=[{'focus':'图例','evidence':[{'section':'s1','passage':'p1'}]}]
                b={'opinions':[{'summary':'图例','facets':[facet]}],'relations':[],'unprocessed':[]}
                run=generate(ws,'bad-range',ReplayProvider([b]))
                self.assertEqual(run['status'],'failed')
                self.assertEqual(run['patch']['edits'],[])
                self.assertIn('E_ATTENTION_SCOPE',str(run['rejected']))
                self.assertEqual([c['stage'] for c in run['calls']],['b_analysis'])
                self.assertTrue(run['unprocessed'])

    def test_multiple_source_fragments_default_to_one_semantic_range(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            original='若无法保留旧图，至少标明版本。'
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':original}],
                'a_reference':{'version':'v','items':[{'id':'version','text':'图示版本说明','locator':'x'}]}})
            b={'opinions':[{'summary':'条件建议','facets':[{'ref':'f1','focus':'标明版本',
                'evidence':[{'section':'s1','passage':'p1'},{'section':'s1','passage':'p2'}],
                'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            scopes=[]
            class Provider(ReplayProvider):
                def complete(self,request):
                    payload=json.loads(request['messages'][1]['content'])
                    if 'sections' in payload:return super().complete(request)
                    if 'selected' in payload:return ReplayProvider([{'function':'修改建议'}]).complete(request)
                    scopes.extend(payload['scopes'])
                    response={'a_text':'图示版本说明','comparisons':{row['id']:{'b_text':row['text'],
                        'kind':'related','reason':'条件下补充版本说明'} for row in payload['scopes']}}
                    return ReplayProvider([response]).complete(request)
            run=generate(ws,'source-group',Provider([b]))
            self.assertEqual(run['status'],'complete',run['errors']+run['rejected'])
            self.assertEqual(len(scopes),1)
            self.assertEqual(scopes[0]['text'],original)
            facet=accept(ws,'source-group',actor='editor',reason='check')['opinions'][0]['facets'][0]
            self.assertEqual(len(facet['a_links']),1)
            self.assertIn('若无法保留旧图',facet['a_links'][0]['scope'])

    def test_decision_labels_have_definitions_in_model_visible_request_prompt(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'数据标签已经清楚。'}],
                'a_reference':{'version':'v','items':[{'id':'new','text':'数据标签是否明确','locator':'x'}]}})
            b={'opinions':[{'summary':'标签','facets':[{'ref':'f1','focus':'数据标签',
                'evidence':[{'section':'s1','passage':'p1'}],'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
            a={'a_text':'数据标签是否明确','comparisons':{'b1':{'b_text':'数据标签已经清楚。','kind':'explicit','reason':'都关注标签的明确性'}}}
            run=generate(ws,'label-contract',ReplayProvider([b,{'function':'实质评价'},a]))
            self.assertEqual(run['status'],'complete',run['errors'])
            function=next(c['request'] for c in run['calls'] if c['stage']=='b_expression')
            schema=function['response_format']['json_schema']['schema']
            prompt=function['messages'][0]['content']
            for label in schema['properties']['function']['enum']:
                self.assertIn(label+'：',prompt)
            self.assertIn('两个或多个可能',prompt)
            mapping=next(c['request'] for c in run['calls'] if c['stage']=='a_mapping')
            a_prompt=mapping['messages'][0]['content']
            choices=mapping['response_format']['json_schema']['schema']['properties']['comparisons']['properties']['b1']['properties']['kind']['enum']
            for label in choices:
                self.assertIn(label+'：',a_prompt)
            extraction=next(c['request'] for c in run['calls'] if c['stage']=='b_analysis')
            self.assertIn('section',extraction['messages'][0]['content'])
            self.assertIn('passage',extraction['messages'][0]['content'])
            self.assertIn('ref',extraction['messages'][0]['content'])
            for field in ('relations[].direction','relations[].scope','relations[].reading','relations[].ambiguity',
                          'unprocessed[].reason','facets[].ranges','ranges[].evidence'):
                self.assertIn(field+'：',extraction['messages'][0]['content'])
            self.assertIn('多个片段不自动成为多个范围',extraction['messages'][0]['content'])

    def test_focused_wire_keeps_unprocessed_reason_separate_from_evidence_selector(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'来源待解释。'}],
                'a_reference':{'version':'none','items':[]}})
            observed=[]
            class Provider(ReplayProvider):
                def complete(self,request):
                    observed.append(request['response_format']['json_schema']['schema']['properties']['unprocessed']['items'])
                    return super().complete(request)
            provider=Provider([{'opinions':[],'relations':[],'unprocessed':[{'section':'s1','reason':'该范围未完成理解'}]}])
            provider.config['protocol']='attention-semantic/4'
            run=generate(ws,'unprocessed-reason',provider)
            self.assertEqual(set(observed[0]['properties']),{'section','reason'})
            self.assertEqual(set(observed[0]['required']),{'section','reason'})
            self.assertEqual(run['errors'],[])
            self.assertEqual(run['unprocessed'][0]['reason'],'该范围未完成理解')

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
                'ranges':[{'focus':'图例','evidence':[{'section':'s1','passage':'p1'}]},
                          {'focus':'检索提示','evidence':[{'section':'s1','passage':'p2'}]}],
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
            self.assertEqual([(a['a_item_id'],a['scope']) for a in f['a_links']],[('labels-new','图例：图例已清楚，')])
            self.assertEqual([o['scope'] for o in f['outside']],['检索提示：请增加检索提示。'])
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
            self.assertEqual(facets[1]['expression']['function'],'含义未定')
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
