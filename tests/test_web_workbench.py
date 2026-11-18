import json
import tempfile
import unittest
import urllib.request
import os
import threading
import time
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

from reviewproto.web_workbench import Workbench
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import ReplayProvider


def post(app,route,data,token=None):
    request=urllib.request.Request(app.origin+route,json.dumps(data).encode(),
        {'Content-Type':'application/json','Origin':app.origin,'X-Attention-Token':token or app.token})
    return json.load(urllib.request.urlopen(request))


class WebWorkbenchTests(unittest.TestCase):
    def test_job_is_bound_to_original_package_and_acceptance_is_explicit(self):
        from test_attention_candidate_ui import prepare
        entered,release=threading.Event(),threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            first=Path(tmp)/'first'; initial,response=prepare(first)
            class HeldProvider(ReplayProvider):
                def complete(self,request):
                    entered.set(); release.wait(10); return super().complete(request)
            with Workbench(Path(tmp)/'data',provider_factory=lambda:HeldProvider([response])) as app:
                original=post(app,'/api/open',{'path':str(first)})
                job=post(app,'/api/generate',{'id':original['id'],'records':[initial['records'][0]['record_id']]})
                self.assertTrue(entered.wait(5))
                other=post(app,'/api/create',{'path':str(Path(tmp)/'other'),'records':[{'text':'另一包原话','anchor':'新'}]})
                try:
                    with self.assertRaises(urllib.error.HTTPError) as caught: post(app,'/api/stop',{})
                    self.assertEqual(caught.exception.code,409)
                finally: release.set()
                deadline=time.monotonic()+15
                while job['status']=='running' and time.monotonic()<deadline:
                    time.sleep(.05);job=post(app,'/api/job',{'job':job['id']})
                self.assertEqual(job['status'],'complete',job)
                before=post(app,'/api/state',{'id':original['id']})
                self.assertEqual(before['state']['opinions'],[])
                preview=post(app,'/api/preview',{'id':original['id'],'run':job['run']})
                self.assertIn('结果尚未保存',urllib.request.urlopen(app.origin+preview['url']).read().decode())
                saved=post(app,'/api/accept',{'id':original['id'],'run':job['run']})
                self.assertEqual(saved['state']['revision'],1)
                self.assertEqual(post(app,'/api/state',{'id':other['id']})['state']['opinions'],[])
                # The result editor token retains its original target too.
                app.project(original['id'])
                self.assertEqual(post(app,'/api/open',{'path':str(first)})['state']['opinions'][0]['interpretation'],'有条件地补充图例')

    def test_credentials_never_returned_or_saved_in_draft_and_missing_key_does_not_schedule(self):
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app:
            with patch('reviewproto.credential.save_deepseek_key') as save:
                value=post(app,'/api/credential',{'key':'SYNTHETIC-SECRET'})
                save.assert_called_once_with('SYNTHETIC-SECRET')
                self.assertEqual(value,{'configured':True})
            html=urllib.request.urlopen(app.url).read().decode()
            self.assertNotIn('SYNTHETIC-SECRET',html)
            self.assertNotIn('SYNTHETIC-SECRET',json.dumps(post(app,'/api/home',{})))
            p=post(app,'/api/create',{'path':str(Path(tmp)/'pack'),'records':[{'text':'合成','anchor':'一'}]})
            from reviewproto.core import ReviewError
            with patch('reviewproto.credential.load_deepseek_key',side_effect=ReviewError('E_DEEPSEEK_CREDENTIAL_MISSING')):
                with self.assertRaises(urllib.error.HTTPError):post(app,'/api/generate',{'id':p['id']})
            self.assertEqual(post(app,'/api/home',{})['jobs'],[])

    def test_sample_has_saved_graph_without_credentials_and_can_be_corrected(self):
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app:
            with patch('reviewproto.credential.load_deepseek_key',side_effect=AssertionError('No model or key needed')):
                sample=post(app,'/api/sample',{})
            state=sample['state']
            self.assertEqual(len(state['records']),2)
            self.assertEqual(len(state['themes']),3)
            self.assertEqual(len(state['opinions']),3)
            self.assertEqual(len(state['a_reference']['items']),2)
            self.assertEqual(post(app,'/api/home',{})['jobs'],[])
            self.assertIn('非专业金标',state['history'][-1]['reason'])
            from copy import deepcopy
            changed=deepcopy(state['opinions'][0])
            edit={key:changed[key] for key in ('opinion_id','record_id','interpretation','status','facets')}
            edit['interpretation']='试用者纠正合成解释'
            patch_data={'schema':'attention-patch/2','analysis_id':state['analysis_id'],
                'base_revision':state['revision'],'actor':'合成试用者','reason':'练习纠正保存','edits':[edit]}
            post(app,'/save',patch_data,app.project(sample['id'])['token'])
            reopened=post(app,'/api/open',{'path':sample['path']})
            self.assertEqual(reopened['state']['opinions'][0]['interpretation'],'试用者纠正合成解释')

    def test_empty_create_preserves_directory_and_stop_closes_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Workbench(Path(tmp)/'data')
            with self.assertRaises(urllib.error.HTTPError):post(app,'/api/create',{'path':str(Path(tmp)/'empty'),'records':[]})
            self.assertFalse((Path(tmp)/'empty').exists())
            self.assertEqual(post(app,'/api/stop',{})['status'],'stopping')
            self.assertTrue(app.closed.wait(5))

    def test_headless_candidate_task_preview_accept_and_return_to_workbench(self):
        from test_attention_candidate_ui import prepare
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory() as tmp:
            initial,response=prepare(Path(tmp)/'pack')
            with Workbench(Path(tmp)/'data',provider_factory=lambda:ReplayProvider([response])) as app,sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'],headless=True)
                page=browser.new_page();page.goto(app.url)
                page.locator('#open-path').fill(str(Path(tmp)/'pack'));page.locator('#open').click()
                page.locator('#project:not([hidden])').wait_for();page.locator('#generate').click()
                expect(page.locator('#jobs')).to_contain_text('待核对，尚未保存',timeout=15000)
                self.assertEqual(app.state(next(iter(app.projects.values())))['opinions'],[])
                page.locator('#jobs a').first.click()
                expect(page.locator('#candidate-preview')).to_contain_text('结果尚未保存')
                page.get_by_role('link',name='返回工作台核对候选').click()
                page.locator('#project:not([hidden])').wait_for()
                page.locator('#runs button').first.click()
                expect(page.locator('#project-meta')).to_contain_text('保存修订 1')
                expect(page.locator('#runs')).to_contain_text('已接收')
                expect(page.locator('#runs button')).to_have_count(0)
                with page.expect_navigation(wait_until='load'):page.locator('#result').click()
                self.assertIn('有条件地补充图例',page.content())
                browser.close()

    def test_workspace_selection_keeps_raw_quote_and_group_and_rejects_replacement(self):
        from legacy_source_fixture import create_legacy_workspace
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app:
            root = Path(tmp)
            source = root / 'source'
            payload = {'scores': [], 'sections': [
                {'section_id': 'ordinary', 'label': '评审意见', 'text': '选中的原话。'}]}
            create_legacy_workspace(source, payload)
            selected = post(app, '/api/source', {'path': str(source)})['sections'][0]
            self.assertEqual(selected['text'], '选中的原话。')
            inputs = {'path': str(root/'pack'), 'records': [
                {'kind': 'workspace', 'workspace': str(source), 'section_id': 'ordinary',
                 'source_selection': selected['source_selection'], 'paper_id': '材料甲'}],
                'a_reference': {'version': '未完A', 'parts': [{'id': 'p', 'label': ''}], 'items': []}}
            post(app, '/api/draft', inputs)
            self.assertEqual(post(app, '/api/home', {})['draft'], inputs)
            built = post(app, '/api/create', inputs)
            self.assertEqual(built['state']['records'][0]['paper_id'], '材料甲')
            self.assertEqual(built['state']['a_reference']['items'], [])
            source.rename(root/'saved-source')
            payload['sections'][0]['text'] = '同路径不同原话。'
            create_legacy_workspace(source, payload)
            inputs['path'] = str(root/'replacement')
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                post(app, '/api/create', inputs)
            self.assertEqual(json.load(rejected.exception)['error'], 'E_ATTENTION_REVALIDATION')
            self.assertFalse((root/'replacement').exists())

    def test_save_requires_current_patch_and_stop_waits_for_transaction_and_response(self):
        from concurrent.futures import ThreadPoolExecutor
        from copy import deepcopy
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app:
            state = post(app, '/api/sample', {})
            token = app.project(state['id'])['token']
            change = deepcopy(state['state']['opinions'][0])
            edit = {key: change[key] for key in ('opinion_id', 'record_id', 'interpretation', 'status', 'facets')}
            edit['interpretation'] = '此次保存仍须完成'
            body = {'schema': 'attention-patch/2', 'analysis_id': state['state']['analysis_id'],
                    'base_revision': state['state']['revision'], 'actor': '合成', 'reason': '停机回归',
                    'edits': [edit]}
            with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                post(app, '/save', body)
            self.assertEqual(unauthorized.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as old_format:
                post(app, '/save', {**body, 'schema': 'attention-patch/1'}, token)
            self.assertEqual(old_format.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as wrong_analysis:
                post(app, '/save', {**body, 'analysis_id': 'another'}, token)
            self.assertEqual(wrong_analysis.exception.code, 400)
            result = Path(state['path']) / 'attention.html'
            result.unlink()
            post(app, '/api/recover', {'id': state['id']})
            self.assertTrue(result.is_file())
            original = AttentionWorkspace.apply
            def held_apply(ws, payload):
                entered.set()
                if not release.wait(5):
                    raise AssertionError('Test failed to release the save')
                return original(ws, payload)
            with patch.object(AttentionWorkspace, 'apply', held_apply), ThreadPoolExecutor(max_workers=2) as pool:
                saved = pool.submit(post, app, '/save', body, token)
                try:
                    self.assertTrue(entered.wait(3))
                    stopped = pool.submit(post, app, '/api/stop', {})
                    self.assertFalse(app.closed.wait(.15))
                    self.assertFalse(stopped.done())
                finally:
                    release.set()
                self.assertEqual(saved.result(5), {'revision': state['state']['revision']+1})
                self.assertEqual(stopped.result(5), {'status': 'stopping'})
            self.assertTrue(app.closed.wait(5))
            self.assertEqual(app.state(app.project(state['id']))['opinions'][0]['interpretation'], '此次保存仍须完成')

    def test_no_browser_launcher_reports_actual_port_and_exits_on_stop(self):
        import subprocess,sys,re
        with tempfile.TemporaryDirectory() as tmp:
            ready=Path(tmp)/'ready.json'
            process=subprocess.Popen([sys.executable,'-m','reviewproto.workbench_launcher','--no-browser','--port','0',
                '--data-dir',str(Path(tmp)/'data'),'--ready-file',str(ready)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+10
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(ready.exists())
                url=json.loads(ready.read_text())['url']
                page=urllib.request.urlopen(url).read().decode()
                token=re.search(r'"token":"([^"]+)"',page).group(1)
                req=urllib.request.Request(url+'api/stop',b'{}',{'Content-Type':'application/json','Origin':url.rstrip('/'),'X-Attention-Token':token})
                self.assertEqual(json.load(urllib.request.urlopen(req))['status'],'stopping')
                stdout,stderr=process.communicate(timeout=5)
                self.assertEqual(process.returncode,0,stderr.decode())
                self.assertEqual(stdout,b'');self.assertEqual(stderr,b'')
            finally:
                if process.poll() is None:process.terminate();process.communicate(timeout=5)

    def test_headless_web_input_draft_dynamic_a_and_manual_saved_result(self):
        from playwright.sync_api import sync_playwright
        from attention_browser import open_editor_tools
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app, sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'],headless=True)
            page=browser.new_page(viewport={'width':1366,'height':768})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(app.url);page.locator('#new').click();page.locator('#destination').fill(str(Path(tmp)/'pack'))
            b=page.locator('#records .record').first
            b.get_by_label('原话定位 / 名称').fill('网页甲')
            b.get_by_label('完整原话').fill('若有条件，保留原话。\n第二行😀 <b>字面标记</b>')
            b.locator('summary').click();b.get_by_role('button',name='加入原分').click()
            b=page.locator('#records .record').first;b.locator('summary').click()
            b.get_by_label('原分标签').fill('自由原分');b.get_by_label('原值（原样保留）').fill(' 7 / 9 ')
            page.locator('#add-b').click();page.locator('#records .record').nth(1).get_by_label('完整原话').fill('第二份不同材料。')
            page.locator('#add-part').click();page.locator('#parts input').first.fill('内容')
            page.locator('#add-part').click();page.locator('#parts input').nth(1).fill('空部分')
            page.locator('#add-a').click();page.locator('#items textarea').fill('必要时说明范围，不强求统一阈值。')
            page.locator('#items').get_by_label('原文定位').fill('合成A第1段')
            page.locator('#save-draft').click()
            page.get_by_text('输入草稿已保存在本机。尚未建立分析。',exact=True).wait_for()
            page.reload();page.locator('#show-input').click()
            self.assertEqual(page.locator('#records textarea').count(),2)
            page.locator('#create').click();page.locator('#project:not([hidden])').wait_for()
            p=next(iter(app.projects.values()));state=app.state(p)
            self.assertEqual(state['records'][0]['scores'],[{'label':'自由原分','raw_value':' 7 / 9 '}])
            self.assertEqual(len(state['a_reference']['parts']),2)
            self.assertEqual(state['records'][0]['text'],'若有条件，保留原话。\n第二行😀 <b>字面标记</b>')
            evidence=os.environ.get('WEB_WORKBENCH_EVIDENCE_DIR')
            if evidence:
                Path(evidence).mkdir(parents=True,exist_ok=True);page.screenshot(path=str(Path(evidence)/'workbench-1366.png'),full_page=True)
            page.locator('#result').click();open_editor_tools(page)
            page.locator('#actor').fill('合成核对者');page.locator('#reason').fill('人工整理原话')
            page.locator('#passage').select_option(index=1);page.locator('#interpretation').fill('有条件地保留原话');page.locator('#stage').click()
            with page.expect_navigation(wait_until='load'):
                with page.expect_response(lambda r:r.url==app.origin+'/save' and r.request.method=='POST') as saved:
                    page.locator('#save').click()
            self.assertEqual(saved.value.status,200)
            page.reload();self.assertIn('有条件地保留原话',page.content())
            self.assertEqual(app.state(p)['revision'],2)  # A import is revision 1.
            for width in (1440,420):
                page.goto(app.url);page.set_viewport_size({'width':width,'height':900})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                if evidence:page.screenshot(path=str(Path(evidence)/('workbench-home-'+str(width)+'.png')),full_page=True)
            self.assertEqual(errors,[])
            browser.close()
    def test_headless_partial_a_survives_home_and_explicit_replacement_shows_target(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app, sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(viewport={'width': 1366, 'height': 768})
            page.goto(app.url)
            page.locator('#new').click()
            page.locator('#destination').fill(str(Path(tmp)/'target'))
            page.locator('#records textarea').fill('合成原话')
            page.locator('#a-version').fill('尚未完成的A')
            page.locator('#add-part').click()
            page.locator('#parts input').fill('尚未填写条文的部分')
            page.locator('#save-draft').click()
            expect(page.locator('#notice')).to_contain_text('输入草稿已保存')
            page.reload()
            page.locator('#show-input').click()
            expect(page.locator('#a-version')).to_have_value('尚未完成的A')
            expect(page.locator('#parts input')).to_have_value('尚未填写条文的部分')
            page.locator('#a-version').fill('未保存的新版本')
            page.locator('#show-home').click()
            page.locator('#show-input').click()
            expect(page.locator('#a-version')).to_have_value('未保存的新版本')
            page.locator('#create').click()
            expect(page.locator('#project-meta')).to_contain_text('尚未提供A参照')
            page.locator('#show-input').click()
            page.locator('#add-a').click()
            page.locator('#items textarea').fill('合成A新条目')
            page.locator('#items').get_by_label('原文定位').fill('合成第1段')
            page.locator('#show-current').click()
            page.get_by_text('维护当前分析', exact=True).click()
            page.locator('#import-a').click()
            expect(page.locator('#a-target')).to_contain_text('target')
            expect(page.locator('#a-confirm-items')).to_contain_text('合成A新条目')
            expect(page.locator('#project-meta')).to_contain_text('尚未提供A参照')
            page.locator('#confirm-a').click()
            expect(page.locator('#project-meta')).to_contain_text('未保存的新版本')
            browser.close()

    def test_main_actions_stay_above_fold_with_long_scope(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app, sync_playwright() as pw:
            path = Path(tmp)/'pack'
            post(app, '/api/create', {'path': str(path), 'records': [
                {'anchor': '合成材料 '+str(i), 'text': '如果证据不足，可以保留原来的判断。\\n'*6}
                for i in range(18)]})
            browser = pw.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(viewport={'width': 1366, 'height': 768})
            page.goto(app.url)
            page.locator('#open-path').fill(str(path))
            page.locator('#open').click()
            expect(page.locator('#scope input')).to_have_count(18)
            for width, height in ((1366, 768), (1440, 900)):
                page.set_viewport_size({'width': width, 'height': height})
                for control in ('#result', '#generate', '#send-scope'):
                    bounds = page.locator(control).bounding_box()
                    self.assertLess(bounds['y']+bounds['height'], height)
                self.assertTrue(page.locator('#scope').evaluate('e=>e.scrollHeight>e.clientHeight'))
                expect(page.locator('#send-scope')).to_have_text('所选原话与当前 A 条文会发送给 DeepSeek')
                evidence = os.environ.get('WEB_WORKBENCH_EVIDENCE_DIR')
                if evidence:
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(evidence)/f'workbench-long-scope-{width}.png'))
            browser.close()

    def test_create_reopen_preserves_input_and_rejects_foreign_origin(self):
        with tempfile.TemporaryDirectory() as tmp, Workbench(Path(tmp)/'data') as app:
            def post(route, data, origin=None):
                request = urllib.request.Request(app.url+route, json.dumps(data).encode(),
                    {'Content-Type':'application/json', 'Origin':origin or app.origin,
                     'X-Attention-Token':app.token})
                return json.load(urllib.request.urlopen(request))
            created=post('api/create', {'path':str(Path(tmp)/'analysis'), 'records':[
                {'anchor':'甲', 'text':'原话\n若有条件，保留。', 'locator':'合成录入',
                 'scores':[{'label':'任意 / 原分','raw_value':'A－'}]}]})
            self.assertEqual(created['state']['records'][0]['sections'][0]['text'], '原话\n若有条件，保留。')
            self.assertEqual(created['state']['a_reference']['items'], [])
            opened=post('api/open', {'path':created['path']})
            self.assertEqual(created['id'], opened['id'])
            with self.assertRaises(urllib.error.HTTPError) as caught:
                post('api/open', {'path':created['path']}, 'http://foreign.invalid')
            self.assertEqual(caught.exception.code,403)
            page=urllib.request.urlopen(app.origin+created['url']).read().decode()
            self.assertIn('attention-session',page)


if __name__=='__main__': unittest.main()
