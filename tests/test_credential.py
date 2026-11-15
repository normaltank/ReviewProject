"""Only synthetic secrets and explicit temporary paths; no real credential file."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reviewproto.credential import load_deepseek_key, save_deepseek_key, credential_available


class Credential(unittest.TestCase):
    def test_environment_precedence_and_late_binding_without_reading_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'missing'
            env={'DEEPSEEK_API_KEY':'SYNTHETIC-ENV-KEY'}
            self.assertEqual(load_deepseek_key(path=target,environ=env),'SYNTHETIC-ENV-KEY')
            self.assertTrue(credential_available(path=target,environ=env))
            env['DEEPSEEK_API_KEY']='CHANGED-FAKE'
            self.assertEqual(load_deepseek_key(path=target,environ=env),'CHANGED-FAKE')
            for value in ('','contains\nnewline','键值'):
                with self.subTest(value=value), self.assertRaisesRegex(Exception,'E_DEEPSEEK_CREDENTIAL_MISSING'):
                    load_deepseek_key(path=target,environ={'DEEPSEEK_API_KEY':value})
            with self.assertRaisesRegex(Exception,'E_DEEPSEEK_CREDENTIAL_MISSING'):
                load_deepseek_key(path=target,environ={})
            self.assertFalse(credential_available(path=target,environ={}))

    @unittest.skipUnless(os.name=='nt','Windows DPAPI needed')
    def test_raw_dpapi_roundtrip_and_wrong_entropy_fail_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'nested/deepseek.dpapi'
            save_deepseek_key('SYNTHETIC-DPAPI-SECRET',path=target)
            self.assertNotIn(b'SYNTHETIC-DPAPI-SECRET',target.read_bytes())
            self.assertTrue(credential_available(path=target,environ={}))
            self.assertEqual(load_deepseek_key(path=target,environ={}),'SYNTHETIC-DPAPI-SECRET')
            with patch('reviewproto.credential.ENTROPY',b'different-test-entropy'):
                with self.assertRaisesRegex(Exception,'E_DEEPSEEK_CREDENTIAL_STORE'):
                    load_deepseek_key(path=target,environ={})
            target.write_bytes(b'invalid synthetic blob')
            with self.assertRaisesRegex(Exception,'E_DEEPSEEK_CREDENTIAL_STORE'):
                load_deepseek_key(path=target,environ={})
