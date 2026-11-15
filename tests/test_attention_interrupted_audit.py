"""Abrupt synthetic provider termination must not erase recorded attempts."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate, ReplayProvider
from reviewproto.cli import main

CHILD = r'''
import os,sys
from pathlib import Path
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate,ReplayProvider
class Interrupted(ReplayProvider):
    def complete(self,request):
        (Path(sys.argv[1])/'fake-dispatched').write_text('synthetic provider entered; no HTTP',encoding='utf-8')
        os._exit(23)
from reviewproto.attention_api_provider import DeepSeekProvider
class InterruptedRepair(DeepSeekProvider):
    def __init__(self):
        super().__init__(credential_loader=lambda:'FAKE-NEVER-READ')
        self.calls=0
    def complete(self,request):
        self.calls+=1
        if self.calls==1:
            return {'choices':[{'message':{'content':'{'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':1,'completion_tokens':2,'total_tokens':3}}
        (Path(sys.argv[1])/'fake-dispatched').write_text('synthetic repair provider entered; no HTTP',encoding='utf-8')
        os._exit(23)
ws=AttentionWorkspace(Path(sys.argv[1])/'pack')
ws.build({'schema':'attention-input/1','records':[{'anchor':'synthetic','visibility':'author_visible','text':'Synthetic comment.'}],
          'a_reference':{'version':'none','items':[]}})
generate(ws,'interrupt',InterruptedRepair() if len(sys.argv)>2 else Interrupted([]))
'''


class InterruptedAudit(unittest.TestCase):
    def interrupted(self,tmp,repair=False):
        child=subprocess.run([sys.executable,'-B','-c',CHILD,tmp]+(['repair'] if repair else []),capture_output=True,text=True,timeout=20)
        self.assertEqual(child.returncode,23,child.stderr)
        self.assertTrue((Path(tmp)/'fake-dispatched').is_file())
        target=Path(tmp)/'pack/candidate-runs/interrupt/run.json'
        return target,json.loads(target.read_text(encoding='utf-8'))

    def test_provider_entry_is_persisted_before_abrupt_exit_and_preview_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,run=self.interrupted(tmp)
            self.assertEqual(run['status'],'running')
            self.assertTrue(run['calls'][0].get('attempted'))
            self.assertEqual(run['request_count'],1)
            self.assertEqual(run['format_repair_count'],0)
            self.assertNotIn('response',run['calls'][0])
            self.assertIsNone(run['calls'][0]['usage'])
            stream=io.StringIO()
            with redirect_stdout(stream):
                code=main(['attention-preview','--workspace',str(Path(tmp)/'pack'),'--run-id','interrupt'])
            self.assertEqual(code,2)
            self.assertIn('requests=1',stream.getvalue())
            self.assertIn('result_and_usage=unknown',stream.getvalue())
            from reviewproto.attention_candidate_ui import CandidateSession
            page=CandidateSession(Path(tmp)/'pack').preview('interrupt').read_text(encoding='utf-8')
            self.assertIn('结果与用量未知',page)
            self.assertIn('不代表服务器已收到',page)
            self.assertEqual(json.loads(target.read_text(encoding='utf-8')),run)

    def test_legacy_unfinished_missing_markers_is_unknown_never_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,run=self.interrupted(tmp)
            for key in ('request_count','format_repair_count','capacity_request_count'):
                run.pop(key,None)
            for key in ('attempted','attempt_started_at'):
                run['calls'][0].pop(key,None)
            run['calls'][0]['status']='pending'
            target.write_text(json.dumps(run),encoding='utf-8')
            stream=io.StringIO()
            with redirect_stdout(stream):
                main(['attention-preview','--workspace',str(Path(tmp)/'pack'),'--run-id','interrupt'])
            self.assertIn('requests=unknown',stream.getvalue())
            self.assertNotIn('requests=0',stream.getvalue())

    def test_missing_totals_are_derived_from_persisted_attempt_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,run=self.interrupted(tmp)
            run.pop('request_count')
            target.write_text(json.dumps(run),encoding='utf-8')
            stream=io.StringIO()
            with redirect_stdout(stream):
                main(['attention-preview','--workspace',str(Path(tmp)/'pack'),'--run-id','interrupt'])
            self.assertIn('requests=1',stream.getvalue())

    def test_interrupted_repair_keeps_original_failure_and_two_persisted_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,run=self.interrupted(tmp,repair=True)
            self.assertEqual(run['request_count'],2)
            self.assertEqual(run['format_repair_count'],1)
            original,repair=run['calls']
            self.assertEqual(original['status'],'failed')
            self.assertEqual(original['error'],'E_ATTENTION_JSON_FORMAT')
            self.assertEqual(repair['parent_call_id'],original['call_id'])
            self.assertTrue(repair['attempted'])
            self.assertNotIn('response',repair)
            self.assertIsNone(repair['usage'])
            self.assertEqual(len(run['errors']),1)

    def test_legacy_repair_missing_totals_and_attempt_marker_previews_unknown(self):
        from reviewproto.attention_candidate_ui import CandidateSession
        with tempfile.TemporaryDirectory() as tmp:
            target,run=self.interrupted(tmp,repair=True)
            for key in ('request_count','format_repair_count','capacity_request_count'):
                run.pop(key,None)
            repair=run['calls'][1]
            repair.pop('attempted');repair.pop('attempt_started_at')
            repair['status']='pending'
            target.write_text(json.dumps(run),encoding='utf-8')
            stream=io.StringIO()
            with redirect_stdout(stream):
                code=main(['attention-preview','--workspace',str(Path(tmp)/'pack'),'--run-id','interrupt'])
            self.assertEqual(code,2)
            self.assertIn('FORMAT_REPAIR requests=unknown',stream.getvalue())
            self.assertIn('CANDIDATES status=running',stream.getvalue())
            self.assertIn('requests=unknown',stream.getvalue())
            page=CandidateSession(Path(tmp)/'pack').preview('interrupt').read_text(encoding='utf-8')
            self.assertIn('实际请求 未知 次',page)
            self.assertNotIn('实际请求 0 次',page)
            self.assertEqual(json.loads(target.read_text(encoding='utf-8')),run)

    def test_missing_repair_total_is_derived_when_attempt_markers_exist(self):
        from reviewproto.attention_candidate_render import render_candidate_preview
        with tempfile.TemporaryDirectory() as tmp:
            target,run=self.interrupted(tmp,repair=True)
            run.pop('format_repair_count')
            target.write_text(json.dumps(run),encoding='utf-8')
            stream=io.StringIO()
            with redirect_stdout(stream):
                main(['attention-preview','--workspace',str(Path(tmp)/'pack'),'--run-id','interrupt'])
            self.assertIn('FORMAT_REPAIR requests=1',stream.getvalue())
            self.assertIn('实际请求 1 次',render_candidate_preview(run))

    def test_prepare_failure_is_persisted_as_zero_without_entering_provider(self):
        class Broken(ReplayProvider):
            def prepare_request(self,request): raise RuntimeError('synthetic prepare failure')
            def complete(self,request): raise AssertionError('must not enter')
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'说明。'}],
                      'a_reference':{'version':'none','items':[]}})
            run=generate(ws,'prepare',Broken([]))
            self.assertEqual(run['request_count'],0)
            self.assertFalse(run['calls'][0].get('attempted'))
            self.assertEqual(json.loads((ws.path/'candidate-runs/prepare/run.json').read_text(encoding='utf-8'))['request_count'],0)
