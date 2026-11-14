import copy
import tempfile
import unittest
from pathlib import Path
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate, preview, accept, ReplayProvider

class CandidateTests(unittest.TestCase):
    def test_b_only_generation_and_idempotent_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = AttentionWorkspace(Path(tmp)/'pack')
            s = w.build({'schema':'attention-input/1','records':[{'anchor':'note','text':'请标明图例。','visibility':'author_visible'}], 'a_reference':{'version':'none','items':[]}})
            r=s['records'][0]
            ev={'source_id':r['source_id'],'section_id':'note','start':0,'end':6,'quote':'请标明图例。'}
            response={'edits':[{'opinion_id':'o1','record_id':r['record_id'],'interpretation':'图例说明','status':'needs_review','facets':[{'facet_id':'f1','interpretation':'标明图例','status':'needs_review','evidence':[ev]}]}],'themes':[],'relations':[]}
            p=ReplayProvider([response])
            run=generate(w,'demo',p)
            self.assertEqual(run['status'],'complete',str([run['errors'],run['rejected']]))
            self.assertNotIn('a_reference',run['calls'][0]['request']['messages'][1]['content'])
            self.assertEqual(w.state()['revision'],0)
            self.assertEqual(preview(w,'demo')['patch']['edits'][0]['status'],'needs_review')
            self.assertEqual(accept(w,'demo',actor='editor',reason='inspect')['revision'],1)
            self.assertEqual(accept(w,'demo',actor='other',reason='again')['revision'],1)
            w.close()


    def test_valid_candidate_survives_malformed_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                s=w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'解释单位。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
                r=s['records'][0]
                good={'opinion_id':'good','record_id':r['record_id'],'interpretation':'说明单位','status':'needs_review','facets':[{'facet_id':'facet','interpretation':'说明单位','status':'needs_review','evidence':[{'source_id':r['source_id'],'section_id':'s','start':0,'end':5,'quote':'解释单位。'}]}]}
                run=generate(w,'partial',ReplayProvider([{'edits':[good,{'opinion_id':'bad'}],'themes':[],'relations':[]}]))
                self.assertEqual(run['status'],'partial')
                self.assertEqual(len(run['patch']['edits']),1)
                self.assertTrue(run['rejected'])
            finally: w.close()

class CandidateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.w=AttentionWorkspace(Path(self.temp.name)/'pack')
        self.addCleanup(self.w.close)
        self.s=self.w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'保留😀。保留😀。','visibility':'author_visible'}],'a_reference':{'version':'v1','items':[]}})
        self.r=self.s['records'][0]

    def output(self):
        ev={'source_id':self.r['source_id'],'section_id':'s','start':4,'end':8,'quote':'保留😀。'}
        return {'edits':[{'opinion_id':'op','record_id':self.r['record_id'],'interpretation':'第二处保留建议','status':'needs_review','facets':[{'facet_id':'f','interpretation':'保留建议','status':'needs_review','evidence':[ev]}]}],'themes':[],'relations':[]}

    def test_duplicate_unicode_explicit_offsets_and_rejected_hallucination(self):
        response=self.output()
        bad=copy.deepcopy(response['edits'][0]); bad['opinion_id']='bad'; bad['facets'][0]['facet_id']='bad-f'; bad['facets'][0]['evidence'][0]['quote']='改写'
        response['edits'].append(bad)
        run=generate(self.w,'quotes',ReplayProvider([response]))
        self.assertEqual(run['status'],'partial')
        self.assertEqual(len(run['patch']['edits']),1)
        self.assertEqual(run['patch']['edits'][0]['facets'][0]['evidence'][0]['start'],4)
        self.assertEqual(self.w.state()['opinions'],[])

    def test_promotion_rejected_and_capacity_reports_entire_scope(self):
        output=self.output(); output['edits'][0]['status']='confirmed'
        run=generate(self.w,'status',ReplayProvider([output]))
        self.assertEqual(run['status'],'failed')
        self.assertEqual(run['patch']['edits'],[])
        run=generate(self.w,'capacity',ReplayProvider([]),context_chars=1)
        self.assertEqual(run['request_count'],0)
        self.assertEqual(run['status'],'failed')
        self.assertEqual(run['unprocessed'][0]['section_id'],'s')
        self.assertIn('request',run['calls'][0])

    def test_receipt_after_manual_revision_and_stale_draft_rejection(self):
        from reviewproto.core import ReviewError
        run=generate(self.w,'first',ReplayProvider([self.output()]))
        generate(self.w,'stale',ReplayProvider([self.output()]))
        state=accept(self.w,'first',actor='reviewer',reason='check')
        patch=copy.deepcopy(run['patch']); patch.update(base_revision=1,actor='human',reason='correct')
        patch['edits']=copy.deepcopy(state['opinions'])
        for op in patch['edits']:
            for key in ('superseded_by','evidence','facet_id','themes','a_links','outside','expression','qualifiers'): op.pop(key,None)
            op['interpretation']='人工纠正'; op['status']='confirmed'
        self.w.apply(patch)
        self.assertEqual(accept(self.w,'first',actor='different',reason='repeat')['revision'],2)
        self.assertEqual(self.w.state()['opinions'][0]['interpretation'],'人工纠正')
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_REVALIDATION'):
            accept(self.w,'stale',actor='reviewer',reason='stale')

    def test_output_failure_retains_receipt_and_reopen_replay(self):
        from reviewproto.core import ReviewError
        generate(self.w,'recover',ReplayProvider([self.output()]))
        html=self.w.path/'attention.html'; html.unlink(); html.mkdir()
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_OUTPUT_RECOVER'):
            accept(self.w,'recover',actor='reviewer',reason='check')
        self.assertEqual(self.w.state()['revision'],1)
        html.rmdir()
        self.assertEqual(accept(self.w,'recover',actor='different',reason='again')['revision'],1)
        reopened=AttentionWorkspace(self.w.path)
        try: self.assertEqual(preview(reopened,'recover')['status'],'complete')
        finally: reopened.close()

    def test_a_mapping_cannot_rewrite_b_and_maps_multiple_items(self):
        # Build a separate package through the public input interface.
        w=AttentionWorkspace(Path(self.temp.name)/'with-a')
        try:
            w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'保留😀。保留😀。','visibility':'author_visible'}],'a_reference':{'version':'a2','items':[{'id':'x','text':'呈现','locator':'1'},{'id':'y','text':'说明','locator':'2'}]}})
            b=self.output()
            class MappingProvider(ReplayProvider):
                def complete(inner,request):
                    import json
                    payload=json.loads(request['messages'][1]['content'])
                    if 'records' in payload:
                        self.assertNotIn('a_reference',payload)
                        return super(MappingProvider,inner).complete(request)
                    f=payload['b_facets'][0]['facet']
                    links=[{'a_item_id':i,'version':'a2','kind':'related','scope':'仅建议本身','reason':'候选对应','evidence':f['evidence'],'status':'needs_review'} for i in ('x','y')]
                    return ReplayProvider([{'mappings':[{'facet_id':f['facet_id'],'a_links':links,'outside':[]}]}]).complete(request)
            run=generate(w,'mapping',MappingProvider([b]))
            self.assertEqual(run['status'],'complete',run['errors'])
            self.assertEqual(len(run['patch']['edits'][0]['facets'][0]['a_links']),2)
            self.assertEqual(run['patch']['edits'][0]['interpretation'],'第二处保留建议')
            self.assertEqual(len(run['calls']),2)
            saved=accept(w,'mapping',actor='editor',reason='check')
            self.assertTrue(all(x['status']=='needs_review' for x in saved['opinions'][0]['facets'][0]['a_links']))
        finally: w.close()

    def test_local_transport_retains_malformed_raw_response_without_retry(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from reviewproto.attention_candidates import LocalProvider
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                calls.append(inner.rfile.read(int(inner.headers['Content-Length'])))
                inner.send_response(200); inner.end_headers(); inner.wfile.write(b'NOT JSON')
            def log_message(inner,*args): pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            run=generate(self.w,'raw',LocalProvider('http://127.0.0.1:'+str(server.server_port)+'/v1'))
            self.assertEqual(run['status'],'failed')
            self.assertEqual(len(calls),1)
            self.assertEqual(run['calls'][0]['response']['raw_http_body'],'NOT JSON')
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_record_batches_continue_after_oversize_and_keep_all_sections(self):
        import json
        from reviewproto.store import Workspace, encoded
        root=Path(self.temp.name)
        src_input=root/'source.json'
        src_input.write_text(json.dumps({'scores':[], 'sections':[{'section_id':'one','label':'评审意见','text':'说明图例。'},{'section_id':'two','label':'评审意见','text':'列出单位。'}]},ensure_ascii=False),encoding='utf-8')
        src=Workspace(root/'source')
        try: src.run(src_input,'synthetic','json')
        finally: src.close()
        w=AttentionWorkspace(root/'merged')
        try:
            s=w.build({'schema':'attention-input/1','records':[{'anchor':'large','text':'长'*20000,'visibility':'author_visible'}]+[{'kind':'workspace','workspace':'source','section_id':sid} for sid in ('one','two')],'a_reference':{'version':'none','items':[]}},base=root)
            r=s['records'][1]
            ev={'source_id':r['source_id'],'section_id':'two','start':0,'end':5,'quote':'列出单位。'}
            class RecordingProvider(ReplayProvider):
                def complete(inner,request):
                    payload=json.loads(request['messages'][1]['content'])
                    self.assertEqual([s['section_id'] for s in payload['records'][0]['sections']],['one','two'])
                    return super(RecordingProvider,inner).complete(request)
            b={'edits':[{'opinion_id':'op','record_id':r['record_id'],'interpretation':'说明单位','status':'needs_review','facets':[{'facet_id':'f','interpretation':'说明单位','evidence':[ev],'status':'needs_review'}]}],'themes':[],'relations':[]}
            db_before=(w.path/'attention.sqlite3').read_bytes()
            run=generate(w,'batches',RecordingProvider([b]))
            self.assertEqual(run['status'],'partial')
            self.assertEqual(run['request_count'],1)
            self.assertEqual(len(run['coverage']),2)
            self.assertEqual(run['unprocessed'][0]['section_id'],'large')
            self.assertEqual(len(run['patch']['edits']),1)
            self.assertEqual((w.path/'attention.sqlite3').read_bytes(),db_before)
            self.assertEqual(w.state()['revision'],0)
        finally: w.close()

    def test_compound_graph_and_scoped_alternatives_survive_import(self):
        b=self.output(); op=b['edits'][0]; f=op['facets'][0]; ev=f['evidence']
        f['qualifiers']={'conditions':'仅当图示不清','alternatives':['保留原图或附说明，未声称互斥'],'negation':'不要求重做'}
        f['themes']=[{'theme_id':'t','reason':'呈现形式','evidence':ev,'status':'needs_review'}]
        other=copy.deepcopy(f); other.update(facet_id='f2',interpretation='说明保留的范围')
        op['facets'].append(other)
        b['themes']=[{'theme_id':'t','label':'图示呈现','definition':'图示的呈现与解释','parent_ids':[],'status':'needs_review'}]
        b['relations']=[{'relation_id':'rel','type':'alternative','endpoints':[{'facet_id':'f','role':'path'},{'facet_id':'f2','role':'explanation'}],'direction':'f to f2','scope':'仅保留建议','evidence':ev,'reading':'条件范围待核','ambiguity':'备选关系未确认','status':'needs_review'}]
        run=generate(self.w,'graph',ReplayProvider([b]))
        self.assertEqual(run['status'],'complete',run['rejected'])
        state=accept(self.w,'graph',actor='editor',reason='check')
        self.assertEqual(len(state['opinions'][0]['facets']),2)
        self.assertEqual(len(state['themes']),1)
        self.assertEqual(len(state['relations']),1)
        self.assertEqual(state['opinions'][0]['facets'][0]['qualifiers']['negation'],'不要求重做')
        self.assertEqual(state['relations'][0]['scope'],'仅保留建议')

    def test_cli_replay_preview_accept_do_not_print_source(self):
        import subprocess,sys,json
        fixture=Path(self.temp.name)/'responses.json'
        fixture.write_text(json.dumps([self.output()],ensure_ascii=False),encoding='utf-8')
        def cli(*args):
            done=subprocess.run([sys.executable,'-m','reviewproto',*args,'--workspace',str(self.w.path),'--run-id','cli'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(done.returncode,0,done.stderr)
            self.assertNotIn('保留',done.stdout+done.stderr)
            return done.stdout
        self.assertIn('mode=replay',cli('attention-generate','--replay',str(fixture)))
        self.assertEqual(self.w.state()['revision'],0)
        self.assertIn('opinions=1',cli('attention-preview'))
        self.assertIn('revision=1',cli('attention-accept','--actor','editor','--reason','check'))
        self.assertEqual(self.w.state()['revision'],1)

    def test_local_endpoint_and_redirect_are_closed(self):
        import threading
        from http.server import HTTPServer,BaseHTTPRequestHandler
        from reviewproto.attention_candidates import LocalProvider
        from reviewproto.core import ReviewError
        for endpoint in ['https://127.0.0.1:8766/v1','http://localhost:8766/v1','http://127.0.0.2/v1','http://127.0.0.1.evil/v1','http://user@127.0.0.1/v1','http://127.0.0.1/v1?q=a']:
            with self.assertRaises(ReviewError): LocalProvider(endpoint)
        hits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                hits.append('post'); inner.send_response(307); inner.send_header('Location','/follow'); inner.end_headers()
            def do_GET(inner): hits.append('follow'); inner.send_response(200); inner.end_headers()
            def log_message(inner,*args): pass
        server=HTTPServer(('127.0.0.1',0),Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            run=generate(self.w,'redirect',LocalProvider('http://127.0.0.1:'+str(server.server_port)+'/v1'))
            self.assertEqual(run['status'],'failed'); self.assertEqual(hits,['post'])
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_a_rewrite_and_changed_source_reject_without_losing_b(self):
        import json
        from reviewproto.core import ReviewError
        root=Path(self.temp.name); source=root/'input.json'
        source.write_text(json.dumps({'schema':'attention-input/1','records':[{'anchor':'s','text':'保留😀。保留😀。','visibility':'author_visible'}],'a_reference':{'version':'a','items':[{'id':'a','text':'解释范围','locator':'1'}]}},ensure_ascii=False),encoding='utf-8')
        w=AttentionWorkspace(root/'versioned')
        try:
            w.build(input_path=source)
            class RewriteProvider(ReplayProvider):
                def complete(inner,request):
                    data=json.loads(request['messages'][1]['content'])
                    if 'records' in data: return super(RewriteProvider,inner).complete(request)
                    f=data['b_facets'][0]['facet']
                    return ReplayProvider([{'mappings':[{'facet_id':f['facet_id'],'interpretation':'非法改写','a_links':[],'outside':[]}]}]).complete(request)
            run=generate(w,'rewrite',RewriteProvider([self.output()]))
            self.assertEqual(run['status'],'partial')
            self.assertEqual(run['patch']['edits'][0]['interpretation'],'第二处保留建议')
            self.assertEqual(run['patch']['edits'][0]['facets'][0].get('outside',[]),[])
            self.assertTrue(run['unprocessed'])
            source.write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ReviewError,'E_ATTENTION_REVALIDATION'):
                accept(w,'rewrite',actor='editor',reason='changed')
            self.assertEqual(w.state()['revision'],0)
        finally: w.close()

    def test_unique_quotes_can_resolve_null_positions_but_repeats_cannot(self):
        b=self.output(); ev=b['edits'][0]['facets'][0]['evidence'][0]
        ev.update(start=None,end=None,quote='保留😀。保留😀。')
        run=generate(self.w,'unique-null',ReplayProvider([b]))
        self.assertEqual(run['status'],'complete')
        grounded=run['patch']['edits'][0]['facets'][0]['evidence'][0]
        self.assertEqual((grounded['start'],grounded['end']),(0,8))
        b=self.output(); b['edits'][0]['facets'][0]['evidence'][0].update(start=None,end=None)
        run=generate(self.w,'ambiguous-null',ReplayProvider([b]))
        self.assertEqual(run['status'],'failed')
        self.assertIn('E_ATTENTION_QUOTE_AMBIGUOUS',str(run['rejected']))


    def test_overlap_and_half_position_are_not_repaired(self):
        b=self.output(); b['edits'][0]['facets'][0]['evidence'][0].update(start=None,end=8)
        run=generate(self.w,'half-offset',ReplayProvider([b]))
        self.assertEqual(run['status'],'failed')
        w=AttentionWorkspace(Path(self.temp.name)/'overlap')
        try:
            s=w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'aaaa','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
            r=s['records'][0]; b=self.output(); b['edits'][0]['record_id']=r['record_id']
            b['edits'][0]['facets'][0]['evidence'][0].update(source_id=r['source_id'],start=None,end=None,quote='aaa')
            run=generate(w,'overlap',ReplayProvider([b]))
            self.assertEqual(run['status'],'failed')
            self.assertIn('E_ATTENTION_QUOTE_AMBIGUOUS',str(run['rejected']))
        finally:w.close()

class CompactProtocolRegression(unittest.TestCase):
    def test_compact_focus_without_audit_identity_binds_to_canonical_pending_objects(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'note','text':'请注明温度单位，不必增做实验。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
                response={'opinions':[{'summary':'标明温度单位且不增做实验','facets':[{'ref':'f1','reading':'注明温度单位，保留无需增加实验的否定','kind':'content','expression':'建议','boilerplate':False,'evidence':[{'section':'s1','quote':'请注明温度单位，不必增做实验。'}],'qualifiers':{'negation':'不必增做实验'},'themes':[{'label':'单位说明','reason':'涉及温度的单位'}]}]}],'relations':[],'unprocessed':[]}
                run=generate(w,'compact',ReplayProvider([response]))
                self.assertEqual(run['status'],'complete',run['errors'])
                request=json.loads(run['calls'][0]['request']['messages'][1]['content'])
                self.assertEqual(request['sections'][0]['text'],'请注明温度单位，不必增做实验。')
                self.assertEqual(request['sections'][0]['passages'][0]['id'],'p1')
                self.assertNotIn('source_id',json.dumps(request))
                self.assertEqual(run['patch']['edits'][0]['facets'][0]['qualifiers']['negation'],'不必增做实验')
                saved=accept(w,'compact',actor='editor',reason='inspect')
                self.assertEqual(saved['opinions'][0]['status'],'needs_review')
                self.assertEqual(len(saved['themes']),1)
            finally:w.close()

    def test_compact_alias_a_mapping_and_occurrence_grounding(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'note','text':'保留。保留。','visibility':'author_visible'}],'a_reference':{'version':'version-r','items':[{'id':'arbitrary-id','text':'关注保留范围','locator':'local'}]}})
                facet={'ref':'local-reference','reading':'第二处保留建议','kind':'content','expression':'建议','boilerplate':False,'evidence':[{'section':'s1','quote':'保留。','occurrence':2}],'qualifiers':{},'themes':[]}
                b={'opinions':[{'summary':'第二处建议','facets':[facet]}],'relations':[],'unprocessed':[]}
                a={'comparisons':{'a1':{'kind':'related','scope':'保留范围','reason':'内容均涉及保留'}}}
                run=generate(w,'map',ReplayProvider([b,a]))
                self.assertEqual(run['status'],'complete',run['errors'])
                final=run['patch']['edits'][0]['facets'][0]
                self.assertEqual(final['evidence'][0]['start'],3)
                self.assertEqual(final['a_links'][0]['a_item_id'],'arbitrary-id')
                self.assertEqual(final['a_links'][0]['version'],'version-r')
                req=json.loads(run['calls'][1]['request']['messages'][1]['content'])
                self.assertEqual(req['facets'][0]['id'],'f1')
                self.assertEqual(req['reference'][0]['id'],'a1')
                self.assertNotIn('arbitrary-id',json.dumps(req))
            finally:w.close()

    def test_compact_empty_outputs_have_no_spurious_graph_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'note','text':'说明范围。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
                empty={'opinions':[],'relations':[],'unprocessed':[]}
                run=generate(w,'zero',ReplayProvider([empty]))
                self.assertEqual(run['status'],'zero_candidates'); self.assertEqual(run['rejected'],[])
                empty['unprocessed']=[{'section':'s1','reason':'无法解读此段'}]
                run=generate(w,'incomplete',ReplayProvider([empty]))
                self.assertEqual(run['status'],'failed'); self.assertEqual(run['rejected'],[])
                self.assertEqual(run['unprocessed'][0]['section_id'],'note')
            finally:w.close()

    def test_compact_supplied_wrong_offsets_are_not_healed(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'note','text':'补充单位。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
                f={'ref':'f1','reading':'补单位','kind':'content','expression':'建议','boilerplate':False,'evidence':[{'section':'s1','quote':'补充单位。','start':1,'end':5}],'qualifiers':{},'themes':[]}
                b={'opinions':[{'summary':'补单位','facets':[f]}],'relations':[],'unprocessed':[]}
                run=generate(w,'bad-position',ReplayProvider([b]))
                self.assertEqual(run['status'],'failed')
                self.assertIn('E_ATTENTION_QUOTE',str(run['rejected']))
                self.assertNotIn('E_ATTENTION_PATCH',str(run['rejected']))
            finally:w.close()

    def test_preview_marks_changed_input_material_stale(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'input.json'
            source.write_text(json.dumps({'schema':'attention-input/1','records':[{'anchor':'note','text':'说明范围。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}},ensure_ascii=False),encoding='utf-8')
            w=AttentionWorkspace(root/'pack')
            try:
                w.build(input_path=source)
                generate(w,'preview-stale',ReplayProvider([{'opinions':[],'relations':[],'unprocessed':[]}]))
                self.assertEqual(preview(w,'preview-stale')['validity'],'current')
                source.write_text('{}',encoding='utf-8')
                self.assertEqual(w.state()['material_status'],'needs_revalidation')
                self.assertEqual(preview(w,'preview-stale')['validity'],'needs_revalidation')
            finally:w.close()


    def test_legacy_empty_replay_remains_legitimate_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'说明范围。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
                run=generate(w,'zero-legacy',ReplayProvider([{'edits':[],'themes':[],'relations':[]}]))
                self.assertEqual(run['status'],'zero_candidates')
                self.assertEqual(run['rejected'],[])
                self.assertEqual(run['intermediate_protocol'],'attention-canonical-replay/1')
            finally:w.close()

    def test_explicit_passage_selection_and_own_qualifier_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'不必新增。若已有记录，可附说明。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
                def facet(ref,passage,reading,qualifiers):
                    return {'ref':ref,'reading':reading,'kind':'content','expression':'建议','boilerplate':False,'evidence':[{'section':'s1','passage':passage}],'qualifiers':qualifiers,'themes':[]}
                b={'opinions':[{'summary':'否定及有条件说明','facets':[facet('first','p1','不要求新增',{'negation':'不必新增'}),facet('second','p2','已有记录时可附说明',{'conditions':'若已有记录','negation':'不必新增'})]}],'relations':[],'unprocessed':[]}
                run=generate(w,'passage',ReplayProvider([b]))
                self.assertEqual(run['status'],'partial')
                saved=accept(w,'passage',actor='editor',reason='inspect')
                facets=saved['opinions'][0]['facets']
                self.assertEqual(facets[1]['evidence'][0]['start'],5)
                self.assertEqual(facets[1]['evidence'][0]['quote'],'若已有记录，可附说明。')
                self.assertEqual(facets[1]['qualifiers']['conditions'],'若已有记录')
                self.assertEqual(facets[1]['qualifiers']['negation'],'')
                self.assertEqual(run['calls'][0]['evidence_selectors'],{'passage':2,'literal':0})
                self.assertIn('E_ATTENTION_QUALIFIER_SCOPE',str(run['rejected']))
            finally:w.close()

    def test_bad_compact_facet_does_not_discard_valid_compound_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'说明来源。','visibility':'author_visible'}],'a_reference':{'version':'none','items':[]}})
                f={'ref':'f1','reading':'说明来源','kind':'content','expression':'建议','boilerplate':False,'evidence':[{'section':'s1','passage':'p1'}],'qualifiers':{},'themes':[]}
                bad=copy.deepcopy(f); bad.update(ref='f2'); bad['evidence']=[{'section':'s1','passage':'not-known'}]
                run=generate(w,'valid-peer',ReplayProvider([{'opinions':[{'summary':'说明来源','facets':[f,bad]}],'relations':[],'unprocessed':[]}]))
                self.assertEqual(run['status'],'partial')
                self.assertEqual(len(run['patch']['edits'][0]['facets']),1)
                self.assertEqual(run['calls'][0]['converted_b']['edits'][0]['facets'][0]['status'],'needs_review')
            finally:w.close()

    def test_compact_multi_a_comparisons_and_explicit_all_unrelated_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=AttentionWorkspace(Path(tmp)/'pack')
            try:
                w.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'补充图示单位。','visibility':'author_visible'}],'a_reference':{'version':'version-z','items':[{'id':'not-first','text':'关注图示','locator':'1'},{'id':'also-related','text':'关注单位说明','locator':'2'},{'id':'unrelated','text':'关注访谈招募','locator':'3'}]}})
                b={'opinions':[{'summary':'单位说明','facets':[{'ref':'f','reading':'补图示单位','kind':'content','expression':'建议','boilerplate':False,'evidence':[{'section':'s1','passage':'p1'}],'qualifiers':{},'themes':[]}]}],'relations':[],'unprocessed':[]}
                def position(kind): return {'kind':kind,'scope':'图示单位','reason':'比较实际对象'}
                a={'comparisons':{'a1':position('related'),'a2':position('partial'),'a3':position('unrelated')}}
                run=generate(w,'multi',ReplayProvider([b,a]))
                self.assertEqual(run['status'],'complete')
                f=run['patch']['edits'][0]['facets'][0]
                self.assertEqual([x['a_item_id'] for x in f['a_links']],['not-first','also-related'])
                self.assertEqual(f['outside'],[])
                a={'comparisons':{key:position('unrelated') for key in ('a1','a2','a3')}}
                run=generate(w,'outside',ReplayProvider([b,a]))
                self.assertEqual(run['status'],'complete')
                f=run['patch']['edits'][0]['facets'][0]
                self.assertEqual(f['a_links'],[]);self.assertEqual(len(f['outside']),1)
                schema=run['calls'][1]['request']['response_format']['json_schema']['schema']
                self.assertEqual(schema['properties']['comparisons']['required'],['a1','a2','a3'])
            finally:w.close()
