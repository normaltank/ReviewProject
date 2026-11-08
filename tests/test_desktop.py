"""Synthetic checks for the trusted local launcher boundary."""
from pathlib import Path
import tempfile
import json
import unittest
import os
import shutil
import subprocess
from unittest.mock import patch

from reviewproto.core import ReviewError


class DesktopControllerTests(unittest.TestCase):
    def test_open_republishes_current_editor_without_changing_business_state(self):
        from reviewproto.desktop import Controller
        from reviewproto.store import Workspace
        from contextlib import closing
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.json'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': '合成意见。', 'visibility': 'visibility_unknown'}]}), encoding='utf-8')
            c = Controller()
            c.import_source(source, root / 'workspace', 'synthetic', 'json')
            with closing(Workspace(c.path)) as ws:
                before = ws.state()
            (c.path / 'report.html').write_text('<html>old 0.4.3 editor</html>', encoding='utf-8')
            self.assertEqual(c.open_workspace(c.path)['revision'], before['revision'])
            self.assertIn('id="source-pane"', (c.path / 'report.html').read_text(encoding='utf-8'))
            with closing(Workspace(c.path)) as ws:
                self.assertEqual(ws.state(), before)

    def test_gui_stop_passes_expected_identity_as_argument(self):
        from reviewproto.desktop import Controller
        c = Controller()
        c.owns_model = 'a' * 32
        with patch('reviewproto.desktop.Path.read_text', return_value=json.dumps({'run_id': c.owns_model})), \
             patch('reviewproto.desktop.run_process', return_value=subprocess.CompletedProcess([], 0)) as call:
            c.stop_model()
            argv = call.call_args.args[0]
            self.assertEqual(argv[-2:], ['-ExpectedRunId', 'a' * 32])

    @unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell needed')
    def test_stop_script_rejects_replaced_run_under_mutex_without_touching_process_or_state(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scripts').mkdir()
            (root / 'work/local-model').mkdir(parents=True)
            target = root / 'scripts/stop-local-model.ps1'
            shutil.copyfile(repo / 'scripts/stop-local-model.ps1', target)
            state = root / 'work/local-model/server-state.json'
            state.write_text(json.dumps({'run_id': 'b' * 32}), encoding='utf-8')
            before = state.read_bytes()
            harness = root / 'probe.ps1'
            harness.write_text('''$ErrorActionPreference = 'Stop'
function global:Get-CimInstance { throw 'PROCESS_LOOKUP_MUST_NOT_RUN' }
function global:Get-Process { throw 'PROCESS_LOOKUP_MUST_NOT_RUN' }
$caught = ''
try { & (Join-Path $PSScriptRoot 'scripts/stop-local-model.ps1') -ExpectedRunId ('a' * 32) }
catch { $caught = $_.Exception.Message }
if ($caught -cne 'E_MODEL_NOT_OWNED') { throw 'Expected identity mismatch before process lookup' }
Write-Output 'EXPECTED_RUN_REJECTED'
''', encoding='utf-8')
            result = subprocess.run([shutil.which('powershell.exe'), '-NoProfile', '-File', str(harness)],
                                    capture_output=True, text=True, timeout=30, shell=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('EXPECTED_RUN_REJECTED', result.stdout)
            self.assertEqual(state.read_bytes(), before)
            for bad in ['a' * 31, 'A' * 32, 'SYNTHETIC-PRIVATE-ARGUMENT']:
                invalid = subprocess.run([shutil.which('powershell.exe'), '-NoProfile', '-File', str(target),
                                          '-ExpectedRunId', bad], capture_output=True, text=True, timeout=30, shell=False)
                self.assertNotEqual(invalid.returncode, 0)
                self.assertIn('E_MODEL_RUN_ID', invalid.stderr)
                self.assertNotIn(bad, invalid.stdout + invalid.stderr)
                self.assertEqual(state.read_bytes(), before)
    def test_import_apply_reopen_recover_and_unsafe_paths(self):
        from reviewproto.desktop import Controller
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source & space.json'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': '合成意见。', 'visibility': 'visibility_unknown'}]}), encoding='utf-8')
            c = Controller()
            with self.assertRaises(ReviewError):
                c.open_workspace(root / 'missing')
            self.assertFalse((root / 'missing').exists())
            with self.assertRaises(ReviewError):
                c.import_source(source, root, 'synthetic', 'json')
            result = c.import_source(source, root / 'dedicated', 'synthetic', 'json')
            self.assertEqual(result['revision'], 0)
            from reviewproto.store import Workspace
            with __import__('contextlib').closing(Workspace(c.path)) as ws:
                payload = ws.review_template()
            payload.update(actor='synthetic', reason='launcher roundtrip')
            payload['edits'][0]['fields']['object'] = '合成对象'
            target = root / 'patch & plain.json'
            target.write_text(json.dumps(payload), encoding='utf-8')
            self.assertEqual(c.apply_patch(target)['revision'], 1)
            self.assertTrue(c.apply_patch(target)['idempotent'])
            self.assertEqual(c.open_workspace(c.path)['revision'], 1)
            (c.path / 'report.html').write_text('broken', encoding='utf-8')
            self.assertEqual(c.recover()['revision'], 1)
            self.assertIn('合成对象', (c.path / 'report.html').read_text(encoding='utf-8'))
            payload['base_revision'] = 0
            payload['reason'] = 'stale changed payload'
            target.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaisesRegex(ReviewError, 'E_REVISION_CONFLICT'):
                c.apply_patch(target)
            payload['base_revision'] = 1
            payload['source_id'] = 'f' * 64
            target.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaisesRegex(ReviewError, 'E_PATCH_SOURCE'):
                c.apply_patch(target)

    def test_output_failure_reports_committed_state_and_recovery(self):
        from reviewproto.desktop import Controller, safe_message
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.json'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': '合成。', 'visibility': 'visibility_unknown'}]}), encoding='utf-8')
            c = Controller()
            with patch('reviewproto.store.Workspace.publish', side_effect=OSError('private secret')):
                with self.assertRaisesRegex(ReviewError, 'E_OUTPUT_FAILED') as caught:
                    c.import_source(source, root / 'workspace', 'synthetic', 'json')
            self.assertIn('已提交', safe_message(caught.exception))
            self.assertEqual(c.recover()['revision'], 0)
            self.assertTrue((c.path / 'report.html').is_file())

    def test_process_arguments_are_values_and_diagnostics_are_safe(self):
        from reviewproto.desktop import run_process, safe_message
        with patch('reviewproto.desktop.subprocess.run') as call:
            call.return_value.returncode = 0
            run_process(['python', 'source & bad$(echo).json'])
            self.assertEqual(call.call_args.args[0][1], 'source & bad$(echo).json')
            self.assertFalse(call.call_args.kwargs['shell'])
            self.assertTrue(call.call_args.kwargs['cwd'].is_absolute())
        self.assertNotIn('secret', safe_message(ValueError('secret quote C:/private')))
        self.assertIn('重新', safe_message(ReviewError('E_PATCH_REVISION')))

    def test_model_status_is_ingest_derived_and_failed_payload_is_preserved(self):
        from reviewproto.desktop import Controller
        from reviewproto.core import digest
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.json'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': '合成。', 'visibility': 'visibility_unknown'},
                {'section_id': 'private', 'label': '作者不可见', 'text': '私密。', 'visibility': 'internal_only'}]}), encoding='utf-8')
            c = Controller()
            c.import_source(source, root / 'workspace', 'synthetic', 'json')
            from contextlib import closing
            from reviewproto.store import Workspace
            with closing(Workspace(c.path)) as ws:
                state = ws.state()
            def extract(argv):
                self.assertEqual(argv[argv.index('--protocol') + 1], 'v3')
                self.assertEqual(argv[argv.index('--section') + 1], 'comments')
                run_id = argv[argv.index('--run-id') + 1]
                folder = c.path / 'model-artifacts' / run_id
                folder.mkdir(parents=True)
                payload = {'schema_version': 1, 'source_id': state['source']['source_id'], 'run_id': run_id,
                           'model': 'synthetic', 'extractor': 'synthetic', 'config': {}, 'candidates': [],
                           'sections': [{'section_id': 'comments', 'text_sha256': digest('合成。'.encode())}],
                           'status': 'failed', 'errors': ['E_SYNTHETIC']}
                (folder / 'candidates.json').write_text(json.dumps(payload), encoding='utf-8')
                return __import__('subprocess').CompletedProcess(argv, 2)
            installed = Path.is_file
            def installed_model(path):
                return True if path.name == 'python.exe' and 'semantic-env' in path.parts else installed(path)
            with patch.object(c, '_check_model'), patch('reviewproto.desktop.Path.is_file', installed_model), \
                 patch('reviewproto.desktop.run_process', side_effect=extract):
                result = c.extract('comments')
                self.assertEqual(result['extraction'], {'status': 'failed', 'accepted': 0, 'rejected': 0})
                with self.assertRaises(ReviewError):
                    c.extract('private')

    def test_stop_refuses_a_service_started_by_another_window(self):
        from reviewproto.desktop import Controller
        c = Controller()
        with self.assertRaises(ReviewError):
            c.stop_model()
        c.owns_model = 'owned-run'
        with patch('reviewproto.desktop.Path.read_text', return_value='{"run_id":"different-run"}'), \
             patch('reviewproto.desktop.run_process') as call:
            with self.assertRaises(ReviewError):
                c.stop_model()
            call.assert_not_called()
        with patch('reviewproto.desktop.run_process') as call:
            call.return_value.returncode = 0
            call.return_value.stdout = b'different-run\n'
            with self.assertRaisesRegex(ReviewError, 'E_MODEL_NOT_OWNED'):
                c.extract('comments')
            self.assertEqual(call.call_count, 1)
