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
