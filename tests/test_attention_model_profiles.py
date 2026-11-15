"""Installed profile engineering checks; no real model service is contacted."""
import tempfile
import unittest
import json
import shutil
import subprocess
from contextlib import closing
from pathlib import Path

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_provider import LocalProvider
from reviewproto.attention_candidates import generate
from test_attention_candidate_capacity import server_for

NINE = 'reviewproject-qwen35-9b-q4km'


class ModelProfiles(unittest.TestCase):
    def test_9b_actual_wire_is_nonthinking_and_retains_full_output_budget(self):
        with server_for(focused=True) as (endpoint, requests), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'感谢修改。'}],
                      'a_reference':{'version':'none','items':[]}})
            run = generate(ws, 'nine', LocalProvider(endpoint, model=NINE))
            self.assertEqual(run['status'], 'complete', run['errors'])
            wire = [body for path, body in requests if path == '/v1/chat/completions']
            self.assertEqual(len(wire), 2)
            for body in wire:
                self.assertEqual(body['model'], NINE)
                self.assertEqual(body['max_tokens'], 4096)
                self.assertEqual(body['chat_template_kwargs'], {'enable_thinking':False})
                self.assertEqual(body['presence_penalty'], 1.5)
                self.assertEqual((body['temperature'],body['top_p'],body['top_k'],body['min_p'],body['seed'],body['cache_prompt']),(.7,.8,20,0,42,False))
                self.assertNotIn('reasoning_budget_tokens',body)
                self.assertNotIn('reasoning_format',body)
            self.assertEqual(run['provider_config']['profile_id'], NINE)

    def test_unknown_alias_cannot_claim_supported_sampling(self):
        with self.assertRaisesRegex(Exception, 'E_ATTENTION_MODEL_PROFILE'):
            LocalProvider(model='handwritten-unknown')

    def test_missing_installation_is_actionable_without_claiming_ownership(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from reviewproto.attention_candidate_ui import CandidateModelService, candidate_message
        with tempfile.TemporaryDirectory() as tmp, patch('reviewproto.desktop.run_powershell') as command:
            command.return_value=SimpleNamespace(returncode=1,stdout=b'',stderr=b'E_MODEL_MISSING')
            service=CandidateModelService()
            with self.assertRaisesRegex(Exception,'E_LOCAL_MODEL_MISSING') as caught:
                service.start(tmp,tmp,NINE)
            self.assertIsNone(service.owned)
            self.assertIn('.tools/local-llm',candidate_message(caught.exception))

    def test_9b_small_output_is_not_rejected_by_4b_thinking_minimum(self):
        with server_for(focused=True) as (endpoint, requests), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':'感谢修改。'}],
                      'a_reference':{'version':'none','items':[]}})
            run = generate(ws,'small-nine',LocalProvider(endpoint,model=NINE,max_tokens=512))
            self.assertEqual(run['status'],'complete',run['errors'])
            self.assertTrue(all(body['max_tokens']==512 for path,body in requests if path=='/v1/chat/completions'))

    def test_ordinary_tk_selects_9b_for_generation_and_start(self):
        import tkinter as tk
        from unittest.mock import patch
        from test_attention_candidate_ui import prepare
        from reviewproto.attention_candidate_ui import AttentionCandidateWindow
        from reviewproto.desktop import Controller
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack'; prepare(path)
            controller=Controller();controller.open_attention(path)
            root=tk.Tk()
            try:
                window=AttentionCandidateWindow(root,controller)
                self.assertIn(NINE, window.model_selector['values'])
                window.model_selector.current(list(window.model_selector['values']).index(NINE))
                self.assertEqual(window.model.get(),NINE)
                captured=[]
                # Capture the ordinary button's submitted operation, without a worker or model request.
                with patch.object(window,'submit',side_effect=lambda action,worker:captured.append((action,worker))), patch.object(window.session,'generate') as generate_call:
                    window.generate_button.invoke()
                    captured.pop()[1]()
                    self.assertEqual(generate_call.call_args.args[1].config['profile_id'],NINE)
                    with patch.object(window.service,'start') as start:
                        window.start_button.invoke();captured.pop()[1]()
                        self.assertEqual(start.call_args.args[-1],NINE)
                window.window.destroy()
            finally:
                root.destroy()
                import gc
                gc.collect()

    def test_service_rejects_9b_receipt_with_wrong_profile_and_keeps_new_failed_launch(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from reviewproto.attention_candidate_ui import CandidateModelService
        from reviewproto.desktop import ROOT
        from reviewproto.local_model_profiles import profile
        p = profile(NINE)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp); run_id = 'd'*32
            state = dict(pid=987,run_id=run_id,repo_root=str(ROOT),owner='ReviewProject/scripts/local-model/v1',
                         profile_id=NINE,model_id=NINE,model_sha256=p['sha256'],model_size=p['size'])
            for correct, exitcode in [(False,0),(False,1),(True,1)]:
                with self.subTest(correct=correct,exitcode=exitcode), patch('reviewproto.desktop.run_powershell') as command:
                    state['profile_id'] = NINE if correct else 'reviewproject-qwen3-4b-q4km'
                    (runtime/'server-state.json').write_text(json.dumps(state),encoding='utf-8')
                    command.return_value = SimpleNamespace(returncode=exitcode,stdout='Owned PID 987 RUN '+run_id)
                    service = CandidateModelService()
                    with self.assertRaises(Exception): service.start(tmp,tmp,NINE)
                    self.assertEqual(service.owned is not None, correct)
                    self.assertEqual(command.call_args.args[0][-2:],['-ModelId',NINE])

    @unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell needed')
    def test_script_lifecycle_fixed_profiles_and_fail_closed_guards(self):
        """Run real scripts in a sandbox with OS process/network boundaries faked."""
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'scripts').mkdir(); (root/'reviewproto').mkdir()
            for name in ('start-local-model.ps1','stop-local-model.ps1','local-model-profile.ps1'):
                shutil.copyfile(repo/'scripts'/name,root/'scripts'/name)
            shutil.copyfile(repo/'reviewproto/local_model_profiles.json',root/'reviewproto/local_model_profiles.json')
            harness = root/'probe.ps1'
            harness.write_text(r'''$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/local-model-profile.ps1')
$resource = Join-Path $PSScriptRoot 'resource'
$llm = Join-Path $resource '.tools/local-llm'
New-Item -ItemType Directory -Path (Join-Path $llm 'llama-b12110-vulkan') -Force | Out-Null
Set-Content (Join-Path $llm 'llama-b12110-vulkan/llama-server.exe') 'fake'
$global:launched = 0; $global:killed = 0; $global:wrongSize = $false; $global:wrongHash = $false
$global:unexpectedListener = $false; $global:portCalls = 0
function global:Get-NetTCPConnection {
    $global:portCalls++
    if ($global:portCalls -gt 1) {
        $id = 777; if ($global:unexpectedListener) { $id = 778 }
        [pscustomobject]@{ OwningProcess=$id; LocalAddress='127.0.0.1' }
    }
}
function global:Get-Item {
    param($LiteralPath)
    if ($LiteralPath -like '*.gguf') {
        $n = $global:selected.size; if ($global:wrongSize) { $n-- }
        return [pscustomobject]@{ Length=$n }
    }
    Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath
}
function global:Get-FileHash {
    param($LiteralPath,$Algorithm)
    if ($LiteralPath -like '*.gguf') {
        $h=$global:selected.sha256; if ($global:wrongHash) { $h='0'*64 }
        return [pscustomobject]@{Hash=$h}
    }
    return [pscustomobject]@{Hash=('1'*64)}
}
function global:Start-Process {
    param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError,[switch]$PassThru)
    $global:launched++; $global:argsSeen=$ArgumentList; $global:exeSeen=$FilePath
    $global:created=[datetime]::UtcNow
    $p=[pscustomobject]@{Id=777;Handle=1;StartTime=$global:created;HasExited=$false}
    $p | Add-Member ScriptMethod Refresh {}; $p | Add-Member ScriptMethod Dispose {}
    return $p
}
function global:Get-CimInstance {
    param($ClassName,$Filter)
    if ($Filter -eq 'ProcessId = 777') { return [pscustomobject]@{ExecutablePath=$global:exeSeen;CommandLine=('exe '+$global:argsSeen)} }
    throw 'UNEXPECTED_PID_LOOKUP'
}
function global:Get-Process {
    param($Id)
    $p=[pscustomobject]@{Id=777;Handle=1;StartTime=$global:created}
    $p | Add-Member ScriptMethod Kill { $global:killed++ }
    $p | Add-Member ScriptMethod WaitForExit { return $true }
    $p | Add-Member ScriptMethod Dispose {}
    return $p
}
function global:Invoke-RestMethod { return [pscustomobject]@{status='ok'} }
foreach ($id in @('reviewproject-qwen3-4b-q4km','reviewproject-qwen35-9b-q4km')) {
    $global:selected=Get-LocalModelProfile $id
    Set-Content (Join-Path $llm $global:selected.filename) 'tiny synthetic weight'
    foreach ($bad in @('size','hash')) {
        $global:wrongSize=$bad -eq 'size'; $global:wrongHash=$bad -eq 'hash'; $global:portCalls=0
        $before=$global:launched; $caught=''
        try { & (Join-Path $PSScriptRoot 'scripts/start-local-model.ps1') -ResourceRoot $resource -RuntimeDir (Join-Path $PSScriptRoot ($id+$bad)) -ModelId $id }
        catch { $caught=$_.Exception.Message }
        if (-not $caught -or $global:launched -ne $before) { throw 'BAD_WEIGHT_WAS_STARTED' }
    }
    $global:wrongSize=$false; $global:wrongHash=$false; $global:portCalls=0
    $runtime=Join-Path $PSScriptRoot $id
    $output=& (Join-Path $PSScriptRoot 'scripts/start-local-model.ps1') -ResourceRoot $resource -RuntimeDir $runtime -ModelId $id
    if (-not ($output -match 'Owned PID 777 RUN')) { throw 'MISSING_NEW_RECEIPT' }
    if (-not $global:argsSeen.Contains(('--alias '+$id+' '))) { throw 'WRONG_ALIAS' }
    $statePath=Join-Path $runtime 'server-state.json'
    $state=Get-Content $statePath -Raw | ConvertFrom-Json
    if ($state.profile_id -cne $id -or $state.model_size -ne $global:selected.size) { throw 'WRONG_STATE' }
    $original=$state | ConvertTo-Json
    $before=$global:killed
    $state.profile_id='wrong-profile'; $state | ConvertTo-Json | Set-Content $statePath
    $caught=''; try { & (Join-Path $PSScriptRoot 'scripts/stop-local-model.ps1') -ResourceRoot $resource -RuntimeDir $runtime -ExpectedRunId $state.run_id } catch {$caught=$_.Exception.Message}
    if (-not $caught -or $global:killed -ne $before) { throw 'BAD_PROFILE_WAS_STOPPED' }
    $original | Set-Content $statePath
    $global:unexpectedListener=$true
    $caught=''; try { & (Join-Path $PSScriptRoot 'scripts/stop-local-model.ps1') -ResourceRoot $resource -RuntimeDir $runtime -ExpectedRunId $state.run_id } catch {$caught=$_.Exception.Message}
    if (-not $caught -or $global:killed -ne $before) { throw 'UNEXPECTED_LISTENER_WAS_STOPPED' }
    $global:unexpectedListener=$false
    # Legacy state without profile fields remains stoppable only for 4B.
    if ($id -eq 'reviewproject-qwen3-4b-q4km') {
        $state=Get-Content $statePath -Raw | ConvertFrom-Json
        $state.PSObject.Properties.Remove('profile_id'); $state.PSObject.Properties.Remove('model_size')
        $state | ConvertTo-Json | Set-Content $statePath
    }
    & (Join-Path $PSScriptRoot 'scripts/stop-local-model.ps1') -ResourceRoot $resource -RuntimeDir $runtime -ExpectedRunId $state.run_id
    if ($global:killed -ne ($before+1)) { throw 'OWNED_STOP_FAILED' }
}
Write-Output 'PROFILE_LIFECYCLE_OK'
''',encoding='utf-8')
            result = subprocess.run([shutil.which('powershell.exe'),'-NoProfile','-File',str(harness)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PROFILE_LIFECYCLE_OK',result.stdout)

