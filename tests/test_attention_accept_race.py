"""Synthetic multi-connection acceptance must keep one immutable receipt."""
import json
import tempfile
import threading
import subprocess
import sys
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from reviewproto.attention import AttentionWorkspace
from reviewproto import attention_candidates as c
from reviewproto.store import atomic, encoded
from reviewproto.core import digest
from test_attention_candidate_ui import prepare


class AcceptRace(unittest.TestCase):
    def build(self,path):
        _,response=prepare(path)
        with closing(AttentionWorkspace(path)) as ws:c.generate(ws,'race',c.ReplayProvider([response]))

    def test_two_prevalidated_connections_keep_receipt_consistent_and_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';self.build(path)
            barrier=threading.Barrier(2);a_done=threading.Event();results={};validate=c._validate
            def gated_validate(state,pa):
                validate(state,pa)
                if pa.get('actor') in ('A','B'):barrier.wait(timeout=10)
            def gated_atomic(target,data):
                if target.name=='acceptance.json' and json.loads(data)['actor']=='B':a_done.wait(10)
                atomic(target,data)
            def worker(actor):
                with closing(AttentionWorkspace(path)) as ws:
                    try:results[actor]=c.accept(ws,'race',actor=actor,reason='reason-'+actor)['revision']
                    except Exception as error:results[actor]=str(error)
                    finally:
                        if actor=='A':a_done.set()
            with patch.object(c,'_validate',gated_validate),patch.object(c,'atomic',gated_atomic):
                threads=[threading.Thread(target=worker,args=(actor,)) for actor in ('A','B')]
                for thread in threads:thread.start()
                for thread in threads:thread.join(15)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(set(results),{'A','B'})
            self.assertTrue(all(value in (1,'E_ATTENTION_OUTPUT_RECOVER') for value in results.values()),results)
            receipt=json.loads((path/'candidate-runs/race/acceptance.json').read_text(encoding='utf-8'))
            with closing(AttentionWorkspace(path)) as ws:
                history=ws.state()['history']
                self.assertEqual(len(history),1)
                self.assertEqual(history[0]['actor'],receipt['actor'])
                self.assertEqual(history[0]['patch'],receipt)
                self.assertEqual(history[0]['fingerprint'],digest((path/'candidate-runs/race/acceptance.json').read_bytes()))
                self.assertEqual(c.accept(ws,'race',actor='repeat',reason='different')['revision'],1)
            from reviewproto.attention_candidate_ui import CandidateSession
            self.assertIn('已在修订 1 接收',CandidateSession(path).preview('race').read_text(encoding='utf-8'))

    def test_cross_process_prevalidated_accepts_apply_one_winner(self):
        script=r'''
import json,sys,time
from pathlib import Path
from reviewproto.attention import AttentionWorkspace
from reviewproto import attention_candidates as c
path=Path(sys.argv[1]);actor=sys.argv[2];original=c._validate
def gate(state,patch):
    original(state,patch)
    (path/('ready-'+actor)).write_text('ready',encoding='utf-8')
    deadline=time.monotonic()+10
    while not (path/'go').exists():
        if time.monotonic()>deadline: raise RuntimeError('test deadline')
        time.sleep(.01)
c._validate=gate
ws=AttentionWorkspace(path)
try:
    result={'revision':c.accept(ws,'race',actor=actor,reason='reason-'+actor)['revision']}
except Exception as error: result={'error':str(error)}
finally:ws.close()
(path/('result-'+actor+'.json')).write_text(json.dumps(result),encoding='utf-8')
'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';self.build(path)
            children=[subprocess.Popen([sys.executable,'-B','-c',script,str(path),actor],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for actor in ('A','B')]
            try:
                deadline=time.monotonic()+10
                while not all((path/('ready-'+actor)).exists() for actor in ('A','B')):
                    if time.monotonic()>deadline:self.fail('children did not prevalidate')
                    time.sleep(.01)
                (path/'go').write_text('go',encoding='utf-8')
                for child in children:
                    _,err=child.communicate(timeout=15)
                    self.assertEqual(child.returncode,0,err.decode('utf-8',errors='replace'))
                outcomes=[json.loads((path/('result-'+actor+'.json')).read_text(encoding='utf-8')) for actor in ('A','B')]
                # Concurrent projection writes may need existing explicit output
                # recovery after DB commit; receipt/history must still agree.
                self.assertTrue(all(outcome in ({'revision':1},{'error':'E_ATTENTION_OUTPUT_RECOVER'}) for outcome in outcomes),outcomes)
                winner=json.loads((path/'candidate-runs/race/acceptance.json').read_text(encoding='utf-8'))
                with closing(AttentionWorkspace(path)) as ws:
                    self.assertEqual(len(ws.state()['history']),1)
                    self.assertEqual(ws.state()['history'][0]['patch'],winner)
                    receipt_bytes=(path/'candidate-runs/race/acceptance.json').read_bytes()
                    self.assertEqual(c.accept(ws,'race',actor='recover',reason='explicit projection recovery')['revision'],1)
                    self.assertEqual((path/'candidate-runs/race/acceptance.json').read_bytes(),receipt_bytes)
            finally:
                for child in children:
                    if child.poll() is None:child.kill();child.communicate(timeout=5)

    def test_published_receipt_recovers_after_apply_failure_and_preserves_first_actor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';self.build(path)
            with closing(AttentionWorkspace(path)) as ws:
                with patch.object(ws,'apply',side_effect=RuntimeError('synthetic interruption before apply')):
                    with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):
                        c.accept(ws,'race',actor='first',reason='first reason')
                receipt=path/'candidate-runs/race/acceptance.json';before=receipt.read_bytes()
                self.assertEqual(ws.state()['revision'],0)
                result=c.accept(ws,'race',actor='later',reason='later reason')
                self.assertEqual(result['revision'],1)
                self.assertEqual(result['history'][0]['actor'],'first')
                self.assertEqual(receipt.read_bytes(),before)

    def test_persistent_receipt_publication_failure_cannot_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';self.build(path)
            with closing(AttentionWorkspace(path)) as ws:
                with patch('reviewproto.attention_candidates.os.link',side_effect=PermissionError('synthetic denied')):
                    with self.assertRaisesRegex(Exception,'^E_ATTENTION_RECEIPT_WRITE$'):
                        c.accept(ws,'race',actor='first',reason='reason')
                self.assertEqual(ws.state()['revision'],0)
                self.assertFalse((path/'candidate-runs/race/acceptance.json').exists())
                self.assertEqual(c.accept(ws,'race',actor='retry',reason='reason')['revision'],1)

    def test_reentrant_loser_applies_published_winner_before_original_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';self.build(path)
            with closing(AttentionWorkspace(path)) as first, closing(AttentionWorkspace(path)) as second:
                original=c._publish_receipt;entered=[]
                def reenter(receipt,data):
                    winner=original(receipt,data)
                    entered.append(c.accept(second,'race',actor='second',reason='other')['revision'])
                    return winner
                with patch.object(c,'_publish_receipt',side_effect=reenter):
                    self.assertEqual(c.accept(first,'race',actor='first',reason='original')['revision'],1)
                self.assertEqual(entered,[1])
                self.assertEqual(first.state()['history'][0]['actor'],'first')

    def test_winner_between_absence_check_and_prevalidation_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';self.build(path)
            with closing(AttentionWorkspace(path)) as first, closing(AttentionWorkspace(path)) as second:
                original=Path.exists;triggered=[]
                def publish_during_absence(target):
                    if target.name=='acceptance.json' and not triggered:
                        triggered.append(True)
                        c.accept(first,'race',actor='first',reason='winner')
                        return False
                    return original(target)
                with patch.object(Path,'exists',publish_during_absence):
                    self.assertEqual(c.accept(second,'race',actor='second',reason='loser')['revision'],1)
                self.assertEqual(second.state()['history'][0]['actor'],'first')
