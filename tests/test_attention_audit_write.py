"""Private synthetic Windows audit locks; no service/credential/GUI operations."""
import json
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from reviewproto.attention_candidates import _call
from reviewproto.attention_provider import ReplayProvider
from reviewproto.core import ReviewError
from reviewproto.local_io import atomic, encoded


class FakeProvider(ReplayProvider):
    def __init__(self):super().__init__([]);self.entered=0
    def complete(self,request):
        self.entered+=1
        return {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}


class AuditWrite(unittest.TestCase):
    def invoke(self,directory,provider,run):
        return _call(directory,run,'a_mapping','Synthetic JSON',{'type':'object'},{'synthetic':True},provider,24000)

    def test_short_reader_lock_released_allows_audit_then_one_provider_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);target=path/'run.json';atomic(target,encoded({'old':'synthetic'}))
            reader=target.open('rb');timers=[];failures=[]
            def release_after_actual_failure(target,data):
                try:return atomic(target,data)
                except PermissionError as error:
                    failures.append(error.winerror)
                    if not timers:
                        timer=threading.Timer(.025,reader.close);timers.append(timer);timer.start()
                    raise
            provider=FakeProvider();run={'calls':[],'errors':[]}
            try:
                with patch('reviewproto.attention_candidates.atomic',side_effect=release_after_actual_failure):
                    self.assertEqual(self.invoke(path,provider,run),{'ok':True})
                self.assertTrue(failures)
                self.assertEqual(provider.entered,1)
                self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['request_count'],1)
            finally:
                for timer in timers:timer.join()
                reader.close()

    def test_persistent_reader_or_readonly_fails_closed_with_safe_audit_code(self):
        for kind in ('reader','readonly'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp);target=path/'run.json';atomic(target,encoded({'old':'synthetic'}))
                reader=target.open('rb') if kind=='reader' else None
                if kind=='readonly':target.chmod(stat.S_IREAD)
                provider=FakeProvider();run={'calls':[],'errors':[],'patch':{'edits':[]}}
                try:
                    with self.assertRaisesRegex(ReviewError,'^E_ATTENTION_AUDIT_WRITE$'):
                        self.invoke(path,provider,run)
                    self.assertEqual(provider.entered,0)
                    self.assertFalse(run['calls'][0]['attempted'])
                    self.assertEqual(run['calls'][0]['error'],'E_ATTENTION_AUDIT_WRITE')
                    self.assertEqual(run['calls'][0]['audit_write_error']['attempts'],3)
                    self.assertEqual(run['patch']['edits'],[])
                finally:
                    if reader:reader.close()
                    target.chmod(stat.S_IWRITE|stat.S_IREAD)

    def test_intent_write_failure_does_not_enter_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);provider=FakeProvider();run={'calls':[],'errors':[]};readers=[]
            def lock_intent(target,data):
                if run['calls'][0]['attempted'] and not readers:readers.append(target.open('rb'))
                return atomic(target,data)
            try:
                with patch('reviewproto.attention_candidates.atomic',side_effect=lock_intent):
                    with self.assertRaisesRegex(ReviewError,'^E_ATTENTION_AUDIT_WRITE$'):
                        self.invoke(path,provider,run)
                self.assertEqual(provider.entered,0)
                saved=json.loads((path/'run.json').read_text(encoding='utf-8'))
                self.assertFalse(saved['calls'][0]['attempted'])
                self.assertEqual(saved['request_count'],0)
            finally:
                for reader in readers:reader.close()

    def test_failed_response_audit_never_resends_completed_provider_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);provider=FakeProvider();run={'calls':[],'errors':[]}
            def response_readonly(target,data):
                if provider.entered and target.exists():target.chmod(stat.S_IREAD)
                return atomic(target,data)
            try:
                with patch('reviewproto.attention_candidates.atomic',side_effect=response_readonly):
                    with self.assertRaisesRegex(ReviewError,'^E_ATTENTION_AUDIT_WRITE$'):
                        self.invoke(path,provider,run)
                self.assertEqual(provider.entered,1)
                saved=json.loads((path/'run.json').read_text(encoding='utf-8'))
                self.assertTrue(saved['calls'][0]['attempted'])
                self.assertNotIn('response',saved['calls'][0])
            finally:(path/'run.json').chmod(stat.S_IWRITE|stat.S_IREAD)
