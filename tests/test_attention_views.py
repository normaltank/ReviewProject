import os
import tempfile
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from reviewproto.attention_render import render
from test_attention_summary import oracle_state

class AttentionViews(unittest.TestCase):
    def test_browser_a_source_list_uses_saved_classifications_without_view_filters(self):
        import copy
        state = oracle_state()
        state.update(material_status='current', history=[])
        state['opinions'] = state['opinions'][:1]
        state['opinions'][0]['interpretation'] = '合成观点'
        state['opinions'][0]['facets'] = state['opinions'][0]['facets'][:1]
        facet = state['opinions'][0]['facets'][0]
        facet['a_links'] = facet['a_links'][:1]
        facet['themes'] = []
        state['themes'] = []
        state['relations'] = []
        for r in state['records']:
            r.update(anchor=r['record_id'], sections=[dict(section_id=r['record_id'], text=r['text'], locator={})])
        for a in state['a_reference']['items']:
            a['locator'] = '合成定位'
        no_link = '尚无当前采用的对应；不表示不关注'
        cases = [
            ('facet-pending', '当前关联：待核对'),
            ('valid', '当前关联：明确对应'),
            ('b-stale', '当前关联：待核对'),
            ('a-stale', '当前关联：待核对'),
            ('old-a-version', '当前关联：待核对'),
            ('link-pending', '当前关联：待核对'),
            ('partial', '当前关联：部分对应'),
            ('related', '当前关联：内容相关'),
            ('undetermined', '当前关联：暂未定'),
            ('withdrawn-link', no_link),
            ('withdrawn-facet', no_link),
            ('withdrawn-opinion', no_link),
            ('superseded-opinion', no_link),
            ('unassigned', no_link),
            ('empty-a', None),
        ]
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            for case, expected in cases:
                with self.subTest(case=case):
                    saved = copy.deepcopy(state)
                    opinion = saved['opinions'][0]
                    facet = opinion['facets'][0]
                    link = facet['a_links'][0]
                    if case == 'facet-pending':
                        facet['status'] = 'needs_review'
                    elif case in ('b-stale', 'a-stale'):
                        saved['material_status'] = 'needs_revalidation'
                        saved['b_material_status'] = 'needs_revalidation' if case == 'b-stale' else 'current'
                        saved['a_material_status'] = 'needs_revalidation' if case == 'a-stale' else 'current'
                    elif case == 'old-a-version':
                        link['version'] = 'synthetic-old-A'
                    elif case == 'link-pending':
                        link['status'] = 'needs_review'
                    elif case in ('partial', 'related', 'undetermined'):
                        link['kind'] = case
                    elif case == 'withdrawn-link':
                        link['status'] = 'withdrawn'
                    elif case == 'withdrawn-facet':
                        facet['status'] = 'withdrawn'
                    elif case in ('withdrawn-opinion', 'superseded-opinion'):
                        opinion['status'] = case.split('-')[0]
                    elif case == 'unassigned':
                        link.update(a_item_id=None, kind='undetermined')
                    elif case == 'empty-a':
                        saved['a_reference']['items'] = []
                        facet['a_links'] = []
                    path = Path(folder) / f'{case}.html'
                    path.write_text(render(saved), encoding='utf-8')
                    page.goto(path.as_uri())
                    page.get_by_text('A条目原文与历史版本', exact=True).click()
                    if expected is None:
                        self.assertIn('A工作参照尚未导入', page.locator('#a-version').inner_text())
                        self.assertEqual(page.locator('#a-items').inner_text(), '')
                    else:
                        self.assertEqual(page.locator('#a-items > p').first.inner_text(), 'P1 · A1 · 合成定位 · ' + expected)
                        self.assertIn(no_link, page.locator('#a-items > p').nth(1).inner_text())
                    original = page.locator('#a-items').inner_text()
                    page.locator('#view-record').select_option('r4')
                    self.assertEqual(page.locator('#view-hits').inner_text(), '命中 0/1 · 无命中记录')
                    self.assertEqual(page.locator('#a-items').inner_text(), original)
                    page.locator('#view-record').select_option('*')
                    page.locator('#view-boiler').select_option('true')
                    self.assertEqual(page.locator('#view-hits').inner_text(), '命中 0/4 · 无命中记录')
                    self.assertEqual(page.locator('#a-items').inner_text(), original)
                    for width in (1440, 420):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.locator('#a-version').scroll_into_view_if_needed()
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                        if expected is not None:
                            bounds = page.locator('#a-items').bounding_box()
                            self.assertGreaterEqual(bounds['x'], 0)
                            self.assertLessEqual(bounds['x'] + bounds['width'], width)
                        evidence = os.environ.get('ATTENTION_REVIEW_FIX_EVIDENCE_DIR')
                        if evidence and case in ('facet-pending', 'valid', 'b-stale', 'old-a-version', 'empty-a'):
                            Path(evidence).mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(Path(evidence) / f'{case}-{width}.png'))
            self.assertEqual(errors, [])
            browser.close()

    def test_browser_saved_views_share_revision_and_record_sets(self):
        state = oracle_state()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'view.html'
            path.write_text(render(state), encoding='utf-8')
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
                page = browser.new_page(offline=True, viewport={'width':1440,'height':1000})
                page.goto(path.as_uri())
                self.assertIn('已保存修订 7', page.get_by_role('region', name='保存结果与筛选').inner_text(timeout=1500))
                self.assertEqual(page.locator('#view-hits').inner_text(), '命中 3/4 · r1、r2、r3')
                browser.close()

    def test_browser_four_record_oracle_filters_matrix_graph_and_keyboard(self):
        import copy
        state = oracle_state()
        # Normalize public saved-state fields used by the incumbent editor.
        state.update(material_status='current', history=[])
        for r in state['records']:
            r.update(anchor=r['record_id'], sections=[dict(section_id=r['record_id'],text=r['text'],locator={})])
        for o in state['opinions']:
            o['interpretation']='合成复合观点'
            for f in o['facets']:
                f.setdefault('outside', [])
                for m in f['themes']:m['reason']='合成成员依据'
        for r in state['relations']:
            r.update(direction='条件仅约束指定动作', reading='合成局部读法', ambiguity='不推反向因果',evidence=[])
            for e in r['endpoints']:e['role']='指定角色'
        # Compound opinion crosses A parts and includes outside content.
        state['opinions'][2]['facets'][0]['status']='needs_review'
        state['opinions'][0]['facets'][1]['outside']=[dict(scope='合成在外范围',reason='清单未明示',status='working',evidence=[])]
        for o in state['opinions']:
            for f in o['facets']:
                for a in f['outside']:a.setdefault('evidence',[])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'view.html';path.write_text(render(state),encoding='utf-8')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'],headless=True)
                page=browser.new_page(offline=True,viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(path.as_uri())
                page.locator('#view-matrix-toggle').check();page.locator('#view-graph-toggle').check()
                self.assertIn('3/4',page.locator('#view-hits').inner_text())
                self.assertIn('已保存修订 7',page.locator('#view-matrix').inner_text())
                edge=page.get_by_role('link',name='关系端点：指定角色',exact=False).first
                line_start=edge.locator('line').evaluate('(e)=>{const p=new DOMPoint(e.x1.baseVal.value,e.y1.baseVal.value).matrixTransform(e.getScreenCTM());return {x:p.x,y:p.y};}')
                aspect=page.locator('#view-graph svg a[href="#view-facet-f1"] rect').bounding_box()
                self.assertAlmostEqual(line_start['x'],aspect['x']+aspect['width'],delta=1)
                self.assertAlmostEqual(line_start['y'],aspect['y']+23,delta=1)
                edge.focus();page.keyboard.press('Enter')
                self.assertIn('不推反向因果',page.locator('#view-detail').inner_text())
                page.locator('#view-matrix-kind').select_option('a')
                r1=page.locator('#view-matrix tbody tr').filter(has=page.get_by_role('rowheader',name='r1',exact=True))
                # P1 explicit is 1 despite two item links; P2 partial and outside coexist.
                self.assertEqual(r1.locator('td').nth(0).locator('span').first.inner_text().strip(),'1 ·')
                self.assertEqual(r1.locator('td').nth(6).locator('span').first.inner_text().strip(),'1 ·')
                self.assertEqual(r1.locator('td').nth(-2).locator('span').first.inner_text().strip(),'1 ·')
                hit=r1.get_by_role('link',name='合成解释',exact=True).first
                hit.focus();page.keyboard.press('Enter')
                self.assertTrue(page.locator('#view-record-r1').evaluate('(e)=>e.open'))
                self.assertEqual(page.locator('#view-record').input_value(),'*')
                page.locator('#view-boiler').select_option('true')
                self.assertEqual(page.locator('#view-hits').inner_text(),'命中 1/4 · r2')
                self.assertNotIn('condition',page.locator('#view-detail').inner_text())
                self.assertIn('reason',page.locator('#view-detail').inner_text())
                page.locator('#view-paper').select_option('"p2"')
                self.assertEqual(page.locator('#view-hits').inner_text(),'命中 0/1 · 无命中记录')
                self.assertIn('0/1',page.locator('#view-summary').inner_text())
                page.locator('#view-boiler').select_option('*');page.locator('#view-record').select_option('r1')
                self.assertEqual(page.locator('#view-hits').inner_text(),'命中 0/0 · 无命中记录')
                self.assertIn('无比例',page.locator('#view-summary').inner_text())
                page.get_by_role('button',name='清除筛选').click()
                page.locator('#view-status').select_option('needs_review')
                self.assertEqual(page.locator('#view-hits').inner_text(),'命中 1/4 · r3')
                page.locator('#view-status').select_option('*');page.locator('#view-direction').select_option('肯定')
                self.assertEqual(page.locator('#view-hits').inner_text(),'命中 1/4 · r2')
                page.get_by_role('button',name='清除筛选').click()
                page.locator('#view-matrix-toggle').uncheck();page.locator('#view-graph-toggle').uncheck()
                self.assertFalse(page.locator('#view-graph').is_visible())
                page.locator('#view-record-r1 > summary').click()
                self.assertIn('合成在外范围',page.locator('#view-detail').inner_text())
                for width in [1440,420]:
                    page.set_viewport_size({'width':width,'height':1000})
                    page.locator('#view-matrix-toggle').check();page.locator('#view-graph-toggle').check()
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                    for selector in ['#view-matrix-hint','#view-graph-hint']:
                        hint=page.locator(selector);hint.scroll_into_view_if_needed()
                        self.assertIn('左右滑动或滚动',hint.inner_text())
                        bounds=hint.bounding_box();self.assertGreaterEqual(bounds['x'],0)
                        self.assertLessEqual(bounds['x']+bounds['width'],width)
                        self.assertGreaterEqual(bounds['y'],0)
                        self.assertLessEqual(bounds['y']+bounds['height'],1000)
                    evidence=os.environ.get('ATTENTION_T5_EVIDENCE_DIR')
                    if evidence:
                        Path(evidence).mkdir(parents=True,exist_ok=True)
                        page.evaluate('scrollTo(0,0)');page.screenshot(path=str(Path(evidence)/f'oracle-{width}-top.png'))
                self.assertEqual(errors,[])
                browser.close()

    def test_browser_download_apply_recover_reopen_keeps_all_saved_views_in_sync(self):
        from reviewproto.attention import AttentionWorkspace
        from reviewproto.desktop import Controller
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ws=AttentionWorkspace(root/'analysis')
            try:
                saved=ws.build(dict(schema='attention-input/1',records=[dict(anchor='synthetic',visibility='visibility_unknown',text='合成原话。',scores=[dict(label='原分',raw_value=' 4.0 ')])],a_reference=dict(version='synthetic',items=[])))
                rid=saved['records'][0]['record_id']
                controller=Controller();controller.open_attention(root/'analysis')
                with sync_playwright() as p:
                    browser=p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'],headless=True)
                    page=browser.new_page(accept_downloads=True,offline=True)
                    page.on('dialog',lambda d:d.accept());page.goto((root/'analysis/attention.html').as_uri())
                    page.locator('#passage').select_option(index=1)
                    page.locator('#interpretation').fill('新增合成解释')
                    page.locator('#actor').fill('合成编辑');page.locator('#reason').fill('合成保存核对')
                    page.locator('#stage').click()
                    page.locator('#view-matrix-toggle').check();page.locator('#view-graph-toggle').check()
                    with page.expect_download() as d:page.locator('#download').click()
                    patch=root/'draft.json';d.value.save_as(patch)
                    self.assertEqual(ws.state()['revision'],0)
                    self.assertEqual(page.locator('#view-hits').inner_text(),'命中 0/1 · 无命中记录')
                    for selector in ['#view-version','#view-matrix','#view-graph']:
                        self.assertIn('已保存修订 0',page.locator(selector).inner_text())
                    controller.apply_attention(patch);controller.recover_attention()
                    page.reload();page.locator('#view-matrix-toggle').check();page.locator('#view-graph-toggle').check()
                    self.assertEqual(page.locator('#view-hits').inner_text(),'命中 1/1 · synthetic')
                    for selector in ['#view-version','#view-matrix','#view-graph']:
                        self.assertIn('已保存修订 1',page.locator(selector).inner_text())
                    page.locator('#view-detail details > summary').first.click()
                    self.assertIn('新增合成解释',page.locator('#view-detail').inner_text())
                    self.assertIn(' 4.0 ',page.locator('#view-detail').text_content())
                    self.assertEqual(page.locator('#view-matrix tbody tr').count(),1)
                    self.assertIn('方面 1 个',page.locator('#view-graph').inner_text())
                    browser.close()
            finally:ws.close()
