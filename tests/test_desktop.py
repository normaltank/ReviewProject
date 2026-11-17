"""Synthetic checks for the trusted local launcher boundary."""
from pathlib import Path
import tempfile
import json
import unittest
import os
import shutil
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from reviewproto.core import ReviewError


class DesktopControllerTests(unittest.TestCase):
    def test_powershell_host_prefers_pwsh_then_falls_back_and_missing_is_safe(self):
        from reviewproto.desktop import powershell_executable
        modern = str(Path('C:/Program Files/PowerShell/7/pwsh.exe').absolute())
        legacy = str(Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe').absolute())
        with patch('reviewproto.desktop.shutil.which', side_effect=lambda name: {'pwsh.exe': modern, 'powershell.exe': legacy}.get(name)) as which:
            self.assertEqual(powershell_executable(), modern)
            which.assert_called_once_with('pwsh.exe')
        with patch('reviewproto.desktop.shutil.which', side_effect=lambda name: legacy if name == 'powershell.exe' else None):
            self.assertEqual(powershell_executable(), legacy)
        with patch('reviewproto.desktop.shutil.which', return_value=None):
            with self.assertRaisesRegex(ReviewError, 'E_LOCAL_MODEL_SETUP'):
                powershell_executable()

    def test_model_start_identity_and_stop_use_same_selected_host(self):
        from reviewproto.desktop import Controller
        selected = str(Path('C:/Program Files/PowerShell/7/pwsh.exe').absolute())
        identity = 'a' * 32
        c = Controller()
        responses = [subprocess.CompletedProcess([], 0, stdout=b'Local model ready; PID 123\n'),
                     subprocess.CompletedProcess([], 0, stdout=identity.encode()),
                     subprocess.CompletedProcess([], 0, stdout=b'Stopped')]
        with patch('reviewproto.desktop.shutil.which', return_value=selected), \
             patch('reviewproto.desktop.Path.read_text', return_value=json.dumps({'run_id': identity, 'pid': 123})), \
             patch('reviewproto.desktop.run_process', side_effect=responses) as call:
            c.start_model()
            c._check_model()
            c.stop_model()
            self.assertEqual([v.args[0][0] for v in call.call_args_list], [selected] * 3)
            self.assertIn('-File', call.call_args_list[0].args[0])
            self.assertIn('-Command', call.call_args_list[1].args[0])
            self.assertEqual(call.call_args_list[2].args[0][-2:], ['-ExpectedRunId', identity])


    def test_gui_stop_passes_expected_identity_as_argument(self):
        from reviewproto.desktop import Controller
        c = Controller()
        c.owns_model = 'a' * 32
        with patch('reviewproto.desktop.Path.read_text', return_value=json.dumps({'run_id': c.owns_model})), \
             patch('reviewproto.desktop.powershell_executable', return_value='synthetic-shell.exe'), \
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


    def test_process_arguments_are_values_and_diagnostics_are_safe(self):
        from reviewproto.desktop import run_process, safe_message
        with patch('reviewproto.desktop.subprocess.run') as call:
            call.return_value.returncode = 0
            run_process(['python', 'source & bad$(echo).json'])
            self.assertEqual(call.call_args.args[0][1], 'source & bad$(echo).json')
            self.assertFalse(call.call_args.kwargs['shell'])
            self.assertTrue(call.call_args.kwargs['cwd'].is_absolute())
            self.assertEqual(call.call_args.kwargs['creationflags'], getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertFalse(call.call_args.kwargs['check'])
            self.assertTrue(call.call_args.kwargs['stdout'].closed)
            self.assertTrue(call.call_args.kwargs['stderr'].closed)
        self.assertNotIn('secret', safe_message(ValueError('secret quote C:/private')))
        self.assertIn('过期', safe_message(ReviewError('E_ATTENTION_CONFLICT')))

    def test_process_closes_output_files_when_spawn_fails(self):
        from reviewproto.desktop import run_process
        with patch('reviewproto.desktop.subprocess.run', side_effect=OSError('synthetic spawn failure')) as call:
            with self.assertRaises(OSError):
                run_process(['synthetic-missing-executable'])
            self.assertTrue(call.call_args.kwargs['stdout'].closed)
            self.assertTrue(call.call_args.kwargs['stderr'].closed)

    def test_process_returns_when_parent_exits_with_inherited_output_still_open(self):
        from reviewproto.desktop import run_process
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ready, release, finished = [root / name for name in ('ready', 'release', 'finished')]
            grandchild = root / 'grandchild.py'
            grandchild.write_text('''from pathlib import Path
import sys
import time
ready, release, finished = map(Path, sys.argv[1:])
print('grandchild stdout', flush=True)
print('grandchild stderr', file=sys.stderr, flush=True)
ready.touch()
deadline = time.monotonic() + 20
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
sys.stdout.close()
sys.stderr.close()
finished.touch()
''', encoding='utf-8')
            parent = root / 'parent.py'
            parent.write_text('''from pathlib import Path
import subprocess
import sys
import time
subprocess.Popen([sys.executable, sys.argv[1], *sys.argv[2:]],
                 stdout=sys.stdout, stderr=sys.stderr, close_fds=False)
deadline = time.monotonic() + 10
while not Path(sys.argv[2]).exists():
    if time.monotonic() >= deadline:
        raise RuntimeError('synthetic grandchild did not start')
    time.sleep(0.02)
print('parent stdout', flush=True)
print('parent stderr', file=sys.stderr, flush=True)
sys.exit(7)
''', encoding='utf-8')
            results, errors = [], []

            def invoke():
                try:
                    results.append(run_process([sys.executable, parent, grandchild, ready, release, finished]))
                except Exception as error:
                    errors.append(error)

            worker = threading.Thread(target=invoke, daemon=True)
            worker.start()
            try:
                worker.join(5)
                self.assertFalse(worker.is_alive(), 'direct parent exited but inherited output blocked run_process')
                self.assertFalse(errors, errors)
                self.assertTrue(ready.is_file())
                self.assertFalse(finished.exists(), 'grandchild must still hold both output handles')
                self.assertEqual(results[0].returncode, 7)
                self.assertIn(b'parent stdout', results[0].stdout)
                self.assertIn(b'grandchild stdout', results[0].stdout)
                self.assertIn(b'parent stderr', results[0].stderr)
                self.assertIn(b'grandchild stderr', results[0].stderr)
            finally:
                # Release only this fixture's grandchild, including on the old
                # pipe-blocking implementation; never touch a model process.
                release.touch()
                worker.join(10)
                deadline = time.monotonic() + 10
                while not finished.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(worker.is_alive(), 'synthetic run_process did not clean up')
                self.assertTrue(finished.is_file(), 'synthetic grandchild did not clean up')


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
        with patch('reviewproto.desktop.powershell_executable', return_value='synthetic-shell.exe'), \
             patch('reviewproto.desktop.run_process') as call:
            call.return_value.returncode = 0
            call.return_value.stdout = b'different-run\n'
            with self.assertRaisesRegex(ReviewError, 'E_MODEL_NOT_OWNED'):
                c._check_model()
            self.assertEqual(call.call_count, 1)
