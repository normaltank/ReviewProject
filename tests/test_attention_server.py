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
    def test_chrome_focus_empty_record_collects_or_blocks_existing_facet_draft(self):
        from playwright.sync_api import sync_playwright, expect
        from attention_browser import open_panel
        import os
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            path = Path(tmp) / 'analysis'
            with closing(AttentionWorkspace(path)) as ws:
                state = ws.build(dict(schema='attention-input/1', records=[dict(anchor='Review '+str(i),
                    text='Synthetic '+str(i)+'.', visibility='author_visible') for i in (1, 2)],
                    a_reference=dict(version='none', items=[])))
                r = state['records'][0]
                ev = dict(source_id=r['source_id'], section_id='Review 1', start=0, end=12, quote='Synthetic 1.')
                ws.apply(dict(schema='attention-patch/2', analysis_id=state['analysis_id'], base_revision=0,
                    actor='合成', reason='预置第一条方面', edits=[dict(opinion_id='o1', record_id=r['record_id'],
                    interpretation='第一条原解释', status='working', facets=[dict(facet_id='f1',
                    interpretation='第一条原解释', evidence=[ev], status='working')])]))
            browser = p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY',
                'C:/Program Files/Google/Chrome/Application/chrome.exe'), headless=True)
            with AttentionSession(path) as session:
                page = browser.new_page()
                page.goto(session.url)
                page.get_by_role('button', name='修改解释', exact=True).click()
                page.locator('#interpretation').fill('')
                page.locator('#focus-list button').nth(1).click()
                page.get_by_role('button', name='修改解释', exact=True).click()
                expect(page.locator('#record option:checked')).to_have_text('记录 1 · Review 1')
                expect(page.locator('#interpretation')).to_have_value('')
                expect(page.locator('#message')).to_contain_text('请选择原话证据，并填写解释')
                expect(page.locator('#page-draft')).to_contain_text('尚未保存')
                page.locator('#interpretation').fill('第一条保留的完整草稿')
                page.get_by_role('button', name='修改解释', exact=True).click()
                expect(page.locator('#record option:checked')).to_have_text('记录 2 · Review 2')
                expect(page.locator('#source')).to_have_text('Synthetic 2.')
                expect(page.locator('#interpretation')).to_have_value('')
                expect(page.locator('#page-draft')).to_contain_text('尚未保存')
                open_panel(page, 'editor-source-position')
                page.locator('#passage').select_option('0:12')
                page.locator('#interpretation').fill('第二条补录解释')
                page.locator('#save').click()
                expect(page.locator('#revision')).to_contain_text('已保存修订 2')
                page.reload()
                for index, interpretation in [(0, '第一条保留的完整草稿'), (1, '第二条补录解释')]:
                    page.locator('#focus-list button').nth(index).click()
                    expect(page.locator('#focus-reading')).to_contain_text(interpretation)
                    page.get_by_role('button', name='修改解释', exact=True).click()
                    expect(page.locator('#interpretation')).to_have_value(interpretation)
                    expect(page.locator('#source')).to_have_text('Synthetic '+str(index+1)+'.')
            with closing(AttentionWorkspace(path)) as ws:
                saved = ws.state()
                self.assertEqual(saved['revision'], 2)
                self.assertEqual(len(saved['opinions']), 2)
                for op in saved['opinions']:
                    index = next(i for i, r in enumerate(saved['records']) if r['record_id'] == op['record_id'])
                    self.assertEqual(op['facets'][0]['evidence'][0]['quote'], 'Synthetic '+str(index+1)+'.')
            browser.close()

    def test_chrome_focus_edit_empty_record_saves_only_selected_record(self):
        from playwright.sync_api import sync_playwright, expect
        from attention_browser import open_panel
        import os
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            path = Path(tmp) / 'analysis'
            with closing(AttentionWorkspace(path)) as ws:
                ws.build(dict(schema='attention-input/1', records=[dict(anchor='Review '+str(i),
                    text='Synthetic '+str(i)+'.', visibility='author_visible') for i in (1, 2)],
                    a_reference=dict(version='none', items=[])))
            browser = p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY',
                'C:/Program Files/Google/Chrome/Application/chrome.exe'), headless=True)
            with AttentionSession(path) as session:
                page = browser.new_page()
                page.goto(session.url)
                page.locator('#focus-list button').nth(1).click()
                page.get_by_role('button', name='修改解释', exact=True).click()
                expect(page.locator('#record option:checked')).to_have_text('记录 2 · Review 2')
                expect(page.locator('#source')).to_have_text('Synthetic 2.')
                open_panel(page, 'editor-source-position')
                page.locator('#passage').select_option('0:12')
                page.locator('#interpretation').fill('第二条补录解释')
                page.locator('#save').click()
                expect(page.locator('#revision')).to_contain_text('已保存修订 1')
                page.reload()
                page.locator('#focus-list button').nth(0).click()
                expect(page.locator('#focus-reading')).to_contain_text('尚无命中解释')
                page.locator('#focus-list button').nth(1).click()
                expect(page.locator('#focus-reading')).to_contain_text('第二条补录解释')
                page.get_by_role('button', name='修改解释', exact=True).click()
                expect(page.locator('#source')).to_have_text('Synthetic 2.')
                expect(page.locator('#interpretation')).to_have_value('第二条补录解释')
            with closing(AttentionWorkspace(path)) as ws:
                saved = ws.state()
                self.assertEqual(saved['revision'], 1)
                self.assertEqual(len(saved['opinions']), 1)
                self.assertEqual(saved['opinions'][0]['record_id'], saved['records'][1]['record_id'])
                self.assertEqual(saved['opinions'][0]['facets'][0]['evidence'][0]['quote'], 'Synthetic 2.')
            browser.close()

    def test_chrome_a_navigation_edits_each_selected_link_once_then_reopens(self):
        from playwright.sync_api import sync_playwright, expect
        from attention_browser import open_editor_tools
        import os
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY','C:/Program Files/Google/Chrome/Application/chrome.exe'),headless=True)
            # Cover updates within each list and conversions out of either list.
            for initial_kind,edited_kind in [('outside','outside'),('partial','related'),('outside','explicit'),('undetermined','outside')]:
                with self.subTest(initial_kind=initial_kind,edited_kind=edited_kind):
                    path=Path(tmp)/(initial_kind+'-'+edited_kind)
                    with closing(AttentionWorkspace(path)) as ws:
                        state=ws.build({'schema':'attention-input/1','records':[{'anchor':'S','visibility':'author_visible','text':'证据不足。','scores':[]}],'a_reference':{'version':'v1','items':[{'id':'a','text':'可以说明证据','locator':'synthetic:1'}]}})
                        r=state['records'][0];ev=dict(source_id=r['source_id'],section_id='S',start=0,end=5,quote='证据不足。')
                        links=[dict(scope=scope,reason='分别保留两个范围',evidence=[ev],status='working') for scope in ['FIRST','SECOND']]
                        field='outside' if initial_kind=='outside' else 'a_links'
                        if field=='a_links':
                            for link in links:link.update(a_item_id='a',version='v1',kind=initial_kind)
                        ws.apply(dict(schema='attention-patch/2',analysis_id=state['analysis_id'],base_revision=0,actor='合成',reason='初始化两个关联',edits=[dict(opinion_id='op',record_id=r['record_id'],interpretation='证据范围',status='working',facets=[dict(facet_id='f',interpretation='证据范围',status='working',evidence=[ev],**{field:links})])]))
                    with AttentionSession(path) as session:
                        page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(session.url);open_editor_tools(page);page.locator('#opinion').select_option('op')
                        page.locator('#a-link').select_option(field+':0')
                        page.locator('#a-scope').fill('FIRST-EDITED')
                        page.locator('#a-kind').select_option(edited_kind)
                        if edited_kind!='outside':page.locator('#a-item').select_option('a')
                        # Do not stage first: selecting the second item must collect it
                        # while still opening the item the user actually selected.
                        page.locator('#a-link').select_option(field+':1')
                        expect(page.locator('#a-scope')).to_have_value('SECOND')
                        expect(page.locator('#a-kind')).to_have_value(initial_kind)
                        page.locator('#a-scope').fill('SECOND-EDITED')
                        page.locator('#save').click();expect(page.locator('#revision')).to_contain_text('已保存修订 2')
                        page.reload();open_editor_tools(page);page.locator('#opinion').select_option('op')
                        for scope,kind in [('FIRST-EDITED',edited_kind),('SECOND-EDITED',initial_kind)]:
                            value=page.locator('#a-link option').filter(has_text=' · '+scope+' · ').get_attribute('value')
                            page.locator('#a-link').select_option(value)
                            expect(page.locator('#a-scope')).to_have_value(scope)
                            expect(page.locator('#a-kind')).to_have_value(kind)
                        self.assertFalse(errors,errors);page.close()
                    with closing(AttentionWorkspace(path)) as ws:
                        saved=ws.state();self.assertEqual(saved['revision'],2)
                        facet=saved['opinions'][0]['facets'][0]
                        self.assertEqual(sorted(link['scope'] for key in ['a_links','outside'] for link in facet[key]),['FIRST-EDITED','SECOND-EDITED'])
            browser.close()

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

    def test_changed_source_rejects_save_without_discarding_page_draft(self):
        from playwright.sync_api import sync_playwright, expect
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'analysis';source=Path(tmp)/'input.json'
            source.write_text(json.dumps({'schema':'attention-input/1','records':[{'anchor':'S','visibility':'visibility_unknown','text':'证据不足。','scores':[]}],'a_reference':{'version':'none','items':[]}}),encoding='utf-8')
            with closing(AttentionWorkspace(path)) as ws:ws.build(input_path=source)
            with AttentionSession(path) as session,sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY','C:/Program Files/Google/Chrome/Application/chrome.exe'),headless=True)
                page=browser.new_page();page.goto(session.url);page.locator('#attention-editor > summary').click()
                page.locator('#passage').select_option('0:5');page.locator('#interpretation').fill('保留来源失效前的草稿')
                source.write_text('{}',encoding='utf-8')
                page.locator('#save').click()
                expect(page.locator('#message')).to_contain_text('E_ATTENTION_REVALIDATION')
                expect(page.locator('#interpretation')).to_have_value('保留来源失效前的草稿')
                self.assertTrue(page.locator('#download').is_enabled())
                browser.close()
            with closing(AttentionWorkspace(path)) as ws:
                self.assertEqual(ws.state()['revision'],0)

    def test_one_save_collects_facet_theme_membership_a_and_relation_together(self):
        from playwright.sync_api import sync_playwright, expect
        from attention_browser import open_editor_tools
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'analysis'
            with closing(AttentionWorkspace(path)) as ws:
                state=ws.build({'schema':'attention-input/1','records':[{'anchor':'S','visibility':'visibility_unknown','text':'证据不足。','scores':[]}],'a_reference':{'version':'none','items':[]}})
                r=state['records'][0];ev=dict(source_id=r['source_id'],section_id='S',start=0,end=5,quote='证据不足。')
                ws.apply(dict(schema='attention-patch/2',analysis_id=state['analysis_id'],base_revision=0,actor='合成',reason='初始化',edits=[dict(opinion_id='op',record_id=r['record_id'],interpretation='旧解释',status='needs_review',facets=[dict(facet_id='f',interpretation='旧解释',status='needs_review',evidence=[ev])])]))
            with AttentionSession(path) as session,sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY','C:/Program Files/Google/Chrome/Application/chrome.exe'),headless=True)
                page=browser.new_page();page.goto(session.url);open_editor_tools(page);page.locator('#opinion').select_option('op')
                page.locator('#interpretation').fill('同次保存的解释')
                page.locator('#a-kind').select_option('undetermined');page.locator('#a-scope').fill('证据范围');page.locator('#a-reason').fill('暂不推断A条目')
                page.locator('#theme-label').fill('证据');page.locator('#theme-definition').fill('证据支持范围');page.locator('#member-reason').fill('明说证据不足')
                page.locator('#relation-role').fill('同一方面内的说明');page.locator('#endpoint-add').click()
                for key,value in [('type','reason'),('direction','未定方向'),('scope','仅本方面'),('reading','局部证据判断')]:page.locator('#relation-'+key).fill(value)
                page.locator('#save').click();expect(page.locator('#revision')).to_contain_text('已保存修订 2');browser.close()
            with closing(AttentionWorkspace(path)) as ws:
                saved=ws.state();f=saved['opinions'][0]['facets'][0]
                self.assertEqual(f['interpretation'],'同次保存的解释')
                self.assertEqual(f['a_links'][0]['scope'],'证据范围')
                self.assertEqual(saved['themes'][0]['label'],'证据')
                self.assertEqual(f['themes'][0]['reason'],'明说证据不足')
                self.assertEqual(saved['relations'][0]['reading'],'局部证据判断')
