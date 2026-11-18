"""Bundled defaults use temporary synthetic assets and isolated credentials only."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from reviewproto.web_workbench import Workbench


def request(app, route, data=None):
    connection = http.client.HTTPConnection(app.authority)
    headers = {'Content-Type': 'application/json', 'Origin': app.origin,
               'X-Attention-Token': app.token}
    connection.request('GET' if data is None else 'POST', route,
                       None if data is None else json.dumps(data), headers)
    response = connection.getresponse()
    status, raw = response.status, response.read().decode('utf-8')
    connection.close()
    return status, raw


class TrialDefaultConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.default = self.root / 'trial-config.json'
        for manager in (
            patch.dict(os.environ, {}, clear=True),
            patch('reviewproto.credential.credential_path', return_value=self.root / 'personal.dpapi'),
            patch('reviewproto.credential.trial_config_path', return_value=self.default, create=True),
        ):
            manager.start()
            self.addCleanup(manager.stop)

    def test_default_is_ready_without_exposing_secret_or_starting_requests(self):
        self.default.write_text(json.dumps({'deepseek_api_key': 'DUMMY-TRIAL-KEY'}), encoding='utf-8')
        with Workbench(self.root / 'data') as app, patch('urllib.request.build_opener') as network:
            status, raw = request(app, '/api/configuration')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw), {'configured': True, 'source': 'trial'})
            self.assertNotIn('DUMMY-TRIAL-KEY', raw)
            self.assertNotIn('DUMMY-TRIAL-KEY', request(app, '/')[1])
            self.assertNotIn('DUMMY-TRIAL-KEY', request(app, '/api/home', {})[1])
            network.assert_not_called()

    def test_explicit_analysis_uses_default_and_keeps_it_out_of_package(self):
        from test_attention_candidate_ui import prepare
        self.default.write_text(json.dumps({'deepseek_api_key': 'DUMMY-TRIAL-KEY'}), encoding='utf-8')
        pack=self.root / 'pack'
        prepare(pack)
        class Response:
            status=200
            def read(self, limit):
                return json.dumps({'choices':[{'message':{'content':json.dumps(
                    {'opinions':[], 'relations':[], 'unprocessed':[]})},'finish_reason':'stop'}]}).encode()
            def __enter__(self): return self
            def __exit__(self,*args): pass
        with Workbench(self.root / 'data') as app, patch('urllib.request.build_opener') as transport:
            transport.return_value.open.return_value=Response()
            opened=json.loads(request(app, '/api/open', {'path':str(pack)})[1])
            transport.assert_not_called()
            status, raw=request(app, '/api/generate', {'id':opened['id']})
            self.assertEqual(status,200,raw)
            job=json.loads(raw)
            deadline=time.monotonic()+10
            while job['status']=='running' and time.monotonic()<deadline:
                time.sleep(.02)
                job=json.loads(request(app, '/api/job', {'job':job['id']})[1])
            self.assertEqual(job['status'],'zero_candidates',job)
            sent=transport.return_value.open.call_args.args[0]
            self.assertEqual(sent.get_header('Authorization'),'Bearer DUMMY-TRIAL-KEY')
            self.assertEqual(sent.full_url,'https://api.deepseek.com/chat/completions')
            self.assertNotIn('DUMMY-TRIAL-KEY',request(app, '/api/home', {})[1])
        for file in pack.rglob('*'):
            if file.is_file():
                self.assertNotIn(b'DUMMY-TRIAL-KEY',file.read_bytes(),str(file))

    def test_personal_credential_overrides_default_even_when_default_is_invalid(self):
        from reviewproto.credential import load_deepseek_key, save_deepseek_key
        self.default.write_text('{invalid',encoding='utf-8')
        save_deepseek_key('DUMMY-PERSONAL-KEY')
        self.assertEqual(load_deepseek_key(),'DUMMY-PERSONAL-KEY')
        with Workbench(self.root / 'data') as app:
            status,raw=request(app,'/api/configuration')
            self.assertEqual(json.loads(raw),{'configured':True,'source':'personal'})
            self.assertNotIn('DUMMY-PERSONAL-KEY',raw)

    def test_missing_or_invalid_default_is_not_reported_ready_and_cannot_schedule(self):
        cases=[(None,'E_DEEPSEEK_CREDENTIAL_MISSING'),('{bad','E_DEEPSEEK_TRIAL_CONFIG'),
               ('{}','E_DEEPSEEK_TRIAL_CONFIG'), ('[]','E_DEEPSEEK_TRIAL_CONFIG'),
               ('{"deepseek_api_key": "bad secret"}','E_DEEPSEEK_TRIAL_CONFIG')]
        with Workbench(self.root / 'data') as app, patch('urllib.request.build_opener') as transport:
            opened=json.loads(request(app,'/api/create',{'path':str(self.root/'pack'),
                'records':[{'anchor':'一','text':'合成原话'}]})[1])
            for value,error in cases:
                with self.subTest(value=value):
                    if value is not None: self.default.write_text(value,encoding='utf-8')
                    configuration=json.loads(request(app,'/api/configuration')[1])
                    self.assertFalse(configuration['configured'])
                    if value is not None: self.assertEqual(configuration['error'],error)
                    status,raw=request(app,'/api/generate',{'id':opened['id']})
                    self.assertEqual(status,409)
                    self.assertEqual(json.loads(raw),{'error':error})
                    self.assertEqual(json.loads(request(app,'/api/home',{})[1])['jobs'],[])
            transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
