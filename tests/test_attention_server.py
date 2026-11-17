import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_server import AttentionSession

class SessionTests(unittest.TestCase):
    def test_session_save_retry_conflict_and_static_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'analysis'
            with closing(AttentionWorkspace(path)) as ws:
                state = ws.build({'schema':'attention-input/1','records':[{'anchor':'S','visibility':'visibility_unknown','text':'证据不足。','scores':[{'label':'原分','raw_value':' 4 '}]}], 'a_reference':{'version':'none','items':[]}})
            with AttentionSession(path) as session:
                page = urlopen(session.url).read().decode()
                self.assertIn('保存修改', page)
                self.assertNotIn(session.token, (path/'attention.html').read_text('utf-8'))
                r = state['records'][0]
                patch = dict(schema='attention-patch/2',analysis_id=state['analysis_id'],base_revision=0,actor='合成',reason='核对',edits=[dict(opinion_id='op',record_id=r['record_id'],interpretation='证据不足',status='working',facets=[dict(facet_id='f',interpretation='证据不足',status='working',evidence=[dict(source_id=r['source_id'],section_id='S',start=0,end=5,quote='证据不足。')])])])
                def save(p, token=session.token):
                    req = Request(session.url+'save', data=json.dumps(p).encode(), headers={'Content-Type':'application/json','Origin':session.origin,'X-Attention-Token':token})
                    return json.load(urlopen(req))
                from unittest.mock import patch as mock_patch
                with mock_patch('reviewproto.attention.atomic', side_effect=OSError('synthetic output failure')):
                    with self.assertRaises(HTTPError) as failed: save(patch)
                    self.assertEqual(json.load(failed.exception)['error'],'E_ATTENTION_OUTPUT_RECOVER')
                self.assertEqual(save(patch)['revision'],1)
                self.assertEqual(save(patch)['revision'],1)
                patch['reason']='过期修改'
                with self.assertRaises(HTTPError) as error: save(patch)
                self.assertEqual(error.exception.code,409)
                with self.assertRaises(HTTPError) as error: save(patch,'wrong')
                self.assertEqual(error.exception.code,403)
            with closing(AttentionWorkspace(path)) as ws:
                self.assertEqual(ws.state()['records'][0]['scores'][0]['raw_value'],' 4 ')

    def test_chromium_one_save_navigation_reopen_and_closed_session(self):
        from playwright.sync_api import sync_playwright, expect
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'analysis'
            with closing(AttentionWorkspace(path)) as ws:
                state=ws.build({'schema':'attention-input/1','records':[{'anchor':'S','visibility':'visibility_unknown','text':'证据不足。','scores':[{'label':'分','raw_value':' 4 '}]}], 'a_reference':{'version':'none','items':[]}})
                r=state['records'][0]
                ws.apply(dict(schema='attention-patch/2',analysis_id=state['analysis_id'],base_revision=0,actor='合成',reason='初始',edits=[dict(opinion_id='op',record_id=r['record_id'],interpretation='旧解释',status='needs_review',facets=[dict(facet_id='f',interpretation='旧解释',status='needs_review',qualifiers={'degree':'不足'},evidence=[dict(source_id=r['source_id'],section_id='S',start=0,end=5,quote='证据不足。')])])]))
            session=AttentionSession(path)
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY','C:/Program Files/Google/Chrome/Application/chrome.exe'),headless=True)
                    page=browser.new_page(viewport={'width':1200,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(session.url)
                    stale=browser.new_page();stale.goto(session.url)
                    page.locator('#attention-editor > summary').click()
                    page.locator('#opinion').select_option('op')
                    page.locator('#interpretation').fill('新解释，仍保留程度')
                    # Switching away collects valid form input without an extra stage click.
                    page.locator('#opinion').select_option('')
                    page.locator('#opinion').select_option('op')
                    expect(page.locator('#interpretation')).to_have_value('新解释，仍保留程度')
                    page.locator('#interpretation').fill('一次保存的新解释')
                    page.locator('#save').click()
                    expect(page.locator('#revision')).to_contain_text('已保存修订 2')
                    expect(page.locator('#view-detail')).to_contain_text('一次保存的新解释')
                    stale.locator('#attention-editor > summary').click();stale.locator('#opinion').select_option('op')
                    stale.locator('#interpretation').fill('冲突草稿');stale.locator('#save').click()
                    expect(stale.locator('#message')).to_contain_text('E_ATTENTION_CONFLICT')
                    expect(stale.locator('#interpretation')).to_have_value('冲突草稿')
                    stale.close()
                    page.reload()
                    expect(page.locator('#view-detail')).to_contain_text('一次保存的新解释')
                    page.locator('#attention-editor > summary').click();page.locator('#opinion').select_option('op')
                    page.locator('#interpretation').fill('')
                    page.locator('#opinion').select_option('')
                    expect(page.locator('#opinion')).to_have_value('op')
                    expect(page.locator('#interpretation')).to_have_value('')
                    expect(page.locator('#message')).to_contain_text('请选择原话证据')
                    session.close();session=None
                    page.locator('#interpretation').fill('断线草稿');page.locator('#save').click()
                    expect(page.locator('#message')).to_contain_text('连接中断')
                    expect(page.locator('#interpretation')).to_have_value('断线草稿')
                    self.assertFalse(errors,errors)
                    browser.close()
            finally:
                if session:session.close()
            with closing(AttentionWorkspace(path)) as ws:
                saved=ws.state();self.assertEqual(saved['revision'],2)
                self.assertEqual(saved['opinions'][0]['facets'][0]['qualifiers']['degree'],'不足')
                self.assertEqual(saved['opinions'][0]['facets'][0]['status'],'needs_review')
                self.assertEqual(saved['records'][0]['scores'][0]['raw_value'],' 4 ')

    def test_controller_switch_keeps_old_page_bound_and_close_releases_sessions(self):
        from reviewproto.desktop import Controller
        with tempfile.TemporaryDirectory() as tmp:
            paths=[Path(tmp)/name for name in ('first','second')]
            for path in paths:
                with closing(AttentionWorkspace(path)) as ws:
                    ws.build({'schema':'attention-input/1','records':[{'anchor':path.name,'visibility':'visibility_unknown','text':'合成原话。','scores':[]}],'a_reference':{'version':'none','items':[]}})
            controller=Controller()
            try:
                controller.open_attention(paths[0]);first=controller.attention_session()
                controller.open_attention(paths[1]);second=controller.attention_session()
                self.assertNotEqual(first.url,second.url)
                self.assertIn('first',urlopen(first.url).read().decode())
                self.assertIn('second',urlopen(second.url).read().decode())
                with closing(AttentionWorkspace(paths[0])) as ws: state=ws.state()
                patch=dict(schema='attention-patch/2',analysis_id=state['analysis_id'],base_revision=0,actor='合成',reason='旧页固定绑定',themes=[dict(theme_id='t',label='主题',definition='边界',parent_ids=[],status='working')])
                req=Request(first.url+'save',data=json.dumps(patch).encode(),headers={'Content-Type':'application/json','Origin':first.origin,'X-Attention-Token':first.token})
                self.assertEqual(json.load(urlopen(req))['revision'],1)
                with closing(AttentionWorkspace(paths[1])) as ws:self.assertEqual(ws.state()['revision'],0)
                for headers,data in [({'Origin':'http://evil.invalid','Content-Type':'application/json','X-Attention-Token':first.token},b'{}'),({'Origin':first.origin,'Content-Type':'text/plain','X-Attention-Token':first.token},b'{}')]:
                    with self.assertRaises(HTTPError):urlopen(Request(first.url+'save',data=data,headers=headers))
            finally:controller.close()
            from urllib.error import URLError
            with self.assertRaises(URLError):urlopen(first.url,timeout=1)
