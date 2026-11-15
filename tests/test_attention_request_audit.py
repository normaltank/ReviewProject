"""Pure historical JSON audit combinations, without model or GUI operations."""
import copy
import io
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import request_audit
from reviewproto.attention_candidate_render import render_candidate_preview
from reviewproto.cli import main


class RequestAudit(unittest.TestCase):
    def cases(self):
        original={'purpose':'analysis','attempted':True,'status':'failed','response':{'http_status':200}}
        complete={'purpose':'format_repair','attempted':True,'status':'complete','response':{'http_status':200}}
        pending={'purpose':'format_repair','attempted':True,'status':'in_flight'}
        unknown={'purpose':'format_repair','status':'pending'}
        preparing={'purpose':'format_repair','attempted':False,'status':'pending','phase':'prepare'}
        yield 'complete',{'status':'complete','calls':[original,complete]},(2,1,0,False)
        yield 'in flight complete totals',{'status':'running','calls':[original,pending],'request_count':2,'format_repair_count':1},(2,1,1,True)
        yield 'missing totals known markers',{'status':'running','calls':[original,pending]},(2,1,1,True)
        yield 'legacy missing marker and totals',{'status':'running','calls':[original,unknown]},(None,None,None,True)
        yield 'legacy stale zero totals',{'status':'running','calls':[original,unknown],'request_count':0,'format_repair_count':0},(None,None,None,True)
        yield 'prepare failure',{'status':'failed','calls':[{'purpose':'analysis','attempted':False,'status':'failed','phase':'prepare'}]},(0,0,0,False)
        yield 'repair not dispatched',{'status':'running','calls':[original,preparing]},(1,0,0,True)
        yield 'legacy replies prove attempts',{'status':'complete','calls':[{'purpose':'analysis','status':'complete','response':{}},{'purpose':'format_repair','status':'complete','response':{}}]},(2,1,0,False)
        yield 'legacy no call evidence',{'status':'running','calls':[]},(None,0,None,True)

    def test_total_repair_pending_counts_and_displays_use_same_known_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            state=ws.build({'schema':'attention-input/1','records':[{'anchor':'s','text':'Synthetic.','visibility':'author_visible'}],
                            'a_reference':{'version':'none','items':[]}})
            for label,fields,expected in self.cases():
                with self.subTest(label=label):
                    run={'run_id':'audit','snapshot':state,'patch':{'edits':[],'themes':[],'relations':[]},
                         'mode':'remote_api','record_ids':[r['record_id'] for r in state['records']],'errors':[],'rejected':[],**fields}
                    before=copy.deepcopy(run)
                    summary=request_audit(run)
                    self.assertEqual(tuple(summary[key] for key in ('count','format_repair_count','pending_response','unfinished')),expected)
                    page=render_candidate_preview(run)
                    if expected[3]:
                        self.assertIn('已开始而未保存响应的尝试：'+('未知' if expected[2] is None else str(expected[2])),page)
                    out=io.StringIO()
                    with patch('reviewproto.attention_candidates.preview',return_value=run), redirect_stdout(out):
                        main(['attention-preview','--workspace',str(ws.path),'--run-id','audit'])
                    self.assertIn('requests='+('unknown' if expected[0] is None else str(expected[0])),out.getvalue())
                    if any(c.get('purpose')=='format_repair' for c in run['calls']):
                        self.assertIn('FORMAT_REPAIR requests='+('unknown' if expected[1] is None else str(expected[1])),out.getvalue())
                    if expected[3]:
                        self.assertIn('pending_response='+('unknown' if expected[2] is None else str(expected[2])),out.getvalue())
                    self.assertEqual(run,before)
