from attention_browser import select_reading_record
"""Saved-position behavior, using the independent four-record oracle."""
from attention_browser import open_panel
import copy
import unittest
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from reviewproto.attention_render import render
from reviewproto.attention_summary import summarize
from reviewproto.attention_positions import project_positions
from test_attention_summary import oracle_state


def svg_text_collisions(chart):
    return chart.locator('svg').evaluate("""(svg) => {
        const labels = [...svg.querySelectorAll('text')].map(t => [t.textContent, t.getBBox()]);
        return labels.flatMap(([text,a],i) => labels.slice(i+1).flatMap(([other,b]) =>
            Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>2 &&
            Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>2 ? [[text,other]] : []));
    }""")


class Positions(unittest.TestCase):
    def test_map_preserves_multi_aspect_unicode_ranges_optional_a_and_empty_scopes(self):
        from contextlib import closing
        from reviewproto.attention import AttentionWorkspace
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
            with closing(AttentionWorkspace(Path(folder) / 'pack')) as ws:
                state = ws.build(dict(schema='attention-input/1', records=[
                    dict(anchor='内部来源甲', text='😀无需扩大样本。若不能补证，无需扩大样本。', paper_id='甲组', visibility='author_visible'),
                    dict(anchor='内部来源乙', text='无需扩大样本。', paper_id='乙组', visibility='author_visible'),
                    dict(anchor='待处理来源', text='请说明研究局限。', visibility='author_visible')],
                    a_reference=dict(version='合成参照二版', parts=[dict(id='method', label='数据与方法'), dict(id='empty', label='空部分')],
                        items=[dict(id='source', part_id='method', text='必要时说明材料来源及其限制，不强制扩大样本。', locator='合成原文')])) )
                r1, r2, r3 = state['records']
                quote = '无需扩大样本。'
                start = r1['text'].rindex(quote)
                ev = dict(source_id=r1['source_id'], section_id=r1['anchor'], start=start, end=start+len(quote), quote=quote)
                def link(kind):
                    return dict(a_item_id='source', version='合成参照二版', kind=kind, scope='样本规模的局部交集',
                                reason='只解释样本规模，不扩大到材料来源的全部范围', evidence=[ev], status='working')
                f = dict(facet_id='f', interpretation='无需扩大样本，保留否定', evidence=[ev], status='working',
                    qualifiers=dict(conditions='若不能补证', negation='无需扩大样本'), expression=dict(function='具体建议', boilerplate_candidate=False),
                    themes=[dict(theme_id=t, evidence=[ev], reason='样本规模范围', status='working') for t in ('parent','child')],
                    a_links=[link('explicit'),link('related')],
                    outside=[dict(scope='另一局部范围', reason='本版未明示这一局部', evidence=[ev], status='working')])
                f2 = copy.deepcopy(f); f2.update(facet_id='f2', interpretation='第二个有条件方面', a_links=[link('partial')], outside=[])
                ws.apply(dict(schema='attention-patch/2', analysis_id=state['analysis_id'], base_revision=0,
                    actor='合成核对者', reason='保留复合范围',
                    themes=[dict(theme_id='parent', label='方法', definition='父组', parent_ids=[], status='working'),
                            dict(theme_id='child', label='样本规模', definition='仅样本多少', parent_ids=['parent'], status='working')],
                    edits=[dict(opinion_id='o', record_id=r1['record_id'], interpretation='复合观点', status='working', facets=[f,f2]),
                           dict(opinion_id='other', record_id=r2['record_id'], interpretation='其他表达', status='working',
                                facets=[dict(facet_id='other', interpretation='另一种表达', evidence=[dict(source_id=r2['source_id'], section_id=r2['anchor'], start=0, end=len(quote), quote=quote)],
                                             expression=dict(function='其他表达', boilerplate_candidate=None), status='working')])]))
                ws.recover()
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport=dict(width=1440,height=900))
            errors=[]; page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto((Path(folder)/'pack'/'attention.html').as_uri())
            marker=page.locator('[data-map-region="part:method"][data-map-record="'+r1['record_id']+'"]')
            self.assertEqual(marker.count(), 1)
            marker.click()
            reading=page.locator('#focus-reading')
            for text in ('第二个有条件方面','若不能补证','无需扩大样本','明确对应','内容相关','部分对应','本版未明示这一局部','必要时说明材料来源及其限制，不强制扩大样本。'):
                self.assertIn(text, reading.inner_text())
            self.assertEqual(reading.locator('.focus-quote mark').all_text_contents(), [quote])
            # The repeated earlier quote and the astral codepoint stay outside the mark.
            self.assertEqual(reading.locator('.focus-quote blockquote').inner_text(), r1['text'])
            self.assertEqual(page.locator('[data-map-theme="parent"]').count(),0)
            self.assertIn('空部分', page.locator('#attention-map').inner_text())
            self.assertIn('尚无条目', page.locator('#attention-map').inner_text())
            page.locator('#map-a-toggle').uncheck()
            self.assertEqual(page.locator('#attention-map [data-map-record="'+r1['record_id']+'"]').count(),1)
            self.assertIn('未归主题内容',page.locator('#attention-map').inner_text())
            self.assertIn('未处理记录',page.locator('#attention-map').inner_text())
            with page.expect_download() as download:
                page.get_by_role('button', name='导出 PNG', exact=True).click()
            with Image.open(download.value.path()) as png:
                self.assertEqual(png.format,'PNG');self.assertEqual(png.width,1100);self.assertGreater(png.height,200)
            open_panel(page,'view-filters')
            page.locator('#view-record').select_option(r1['record_id'])
            page.locator('#view-function').select_option('其他表达')
            self.assertIn('零命中；分母仍为 1',page.locator('#attention-map').inner_text())
            page.locator('#view-paper').select_option('"乙组"')
            self.assertIn('N=0',page.locator('#attention-map').inner_text())
            with page.expect_download() as download:
                page.get_by_role('button', name='导出 SVG', exact=True).click()
            self.assertIn('N=0',Path(download.value.path()).read_text(encoding='utf-8'))
            self.assertEqual(errors,[])
            browser.close()

    def test_map_is_default_and_exports_all_filtered_record_projections(self):
        state = oracle_state()
        state.update(material_status='current', history=[], bindings=[])
        for r in state['records']:
            r.update(anchor=r['record_id'], sections=[dict(section_id=r['record_id'], text=r['text'], locator={})])
        for o in state['opinions']:
            o['interpretation'] = '合成观点'
            for f in o['facets']:
                for item in f['outside']:
                    item.update(evidence=[], reason='合成范围依据')
        for relation in state['relations']:
            relation.update(evidence=[])
        state['themes'][1]['label'] = '样本来源'
        state['themes'][2]['label'] = '结论范围'
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
            path = Path(folder) / 'map.html'
            path.write_text(render(state), encoding='utf-8')
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport=dict(width=1366, height=768))
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(path.as_uri())
            self.assertTrue(page.locator('#attention-map').is_visible())
            self.assertIn('分母 4', page.locator('#view-positions').inner_text())
            # ROOT is an aggregate parent, never another peer cluster.
            self.assertEqual(page.locator('[data-map-theme="ROOT"]').count(), 0)
            mixed = page.locator('[data-map-record="r2"][data-map-region="part:P1"]')
            self.assertEqual(mixed.count(), 1)
            self.assertIn('明确对应', mixed.get_attribute('aria-label'))
            self.assertIn('内容相关', mixed.get_attribute('aria-label'))
            mixed.click()
            self.assertIn('合成原话', page.locator('#focus-reading').inner_text())
            self.assertGreater(page.locator('[data-map-record="r2"][aria-current="true"]').count(), 1)
            with page.expect_download() as download:
                page.get_by_role('button', name='导出 SVG', exact=True).click()
            exported = Path(download.value.path()).read_text(encoding='utf-8')
            for text in ('分母 4', 'synthetic-A', '修订 7', '样本来源', '结论范围', '未处理'):
                self.assertIn(text, exported)
            self.assertEqual(errors, [])
            browser.close()

    def test_two_and_three_a_parts_keep_long_labels_and_shared_theme_markers_visible(self):
        from playwright.sync_api import expect
        state = oracle_state()
        state.update(material_status='current', history=[], bindings=[])
        for r in state['records']:
            r.update(anchor=r['record_id'], sections=[dict(section_id=r['record_id'], text=r['text'], locator={})])
        for o in state['opinions']:
            o['interpretation'] = '合成观点'
            for f in o['facets']:
                for item in f['outside']:
                    item.update(evidence=[], reason='合成范围依据')
        for relation in state['relations']:
            relation.update(evidence=[])
        state['themes'][1]['label'] = '完整描述材料及样本的来源与边界'
        state['themes'][2]['label'] = '必要时给出结论适用的条件与范围'
        parts, items = state['a_reference']['parts'], state['a_reference']['items']
        parts[0]['label'] = '材料与方法中需保留的具体限定'
        parts[1]['label'] = '结果与结论中仍需核对的范围'
        links = state['opinions'][0]['facets'][1]['a_links']
        links.append(dict(links[0], a_item_id='A1'))
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
            path = Path(folder)/'parts.html'
            browser = pw.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            for count in (2, 3):
                if count == 3:
                    parts.append(dict(id='P3', label='引言与研究问题所依据的定义'))
                    items.append(dict(items[0], id='A5', text='保留相关证据', part_id='P3'))
                    links.append(dict(links[0], a_item_id='A5'))
                path.write_text(render(state), encoding='utf-8')
                for width, height in ((1366, 768), (1440, 900), (420, 768)):
                    with self.subTest(a_parts=count, viewport=(width, height)):
                        page = browser.new_page(offline=True, viewport=dict(width=width, height=height))
                        page.goto(path.as_uri())
                        page.evaluate('document.fonts.ready')
                        chart = page.locator('#attention-map')
                        self.assertEqual(svg_text_collisions(chart), [])
                        for part in parts:
                            expect(chart).to_contain_text(part['label'])
                        marks = chart.locator('[data-map-region="part:P1"][data-map-record="r1"]')
                        expect(marks).to_have_count(2)
                        evidence = os.environ.get('ATTENTION_POSITION_EVIDENCE_DIR')
                        if evidence:
                            Path(evidence).mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(Path(evidence)/f'positions-{count}-parts-{width}.png'))
                        chart.locator('[data-map-region="part:P1"][data-map-record="r2"]').press('Enter')
                        selected_marks = chart.locator('[data-map-region="part:P1"][data-map-record="r1"][aria-current="true"]')
                        expect(selected_marks).to_have_count(0)
                        second_theme = chart.locator('[data-map-theme="T2"] [data-map-region="part:P1"][data-map-record="r1"]')
                        second_theme.press('Enter')
                        expect(second_theme).to_be_focused()
                        expect(selected_marks).to_have_count(2)
                        page.close()
            browser.close()

    def test_dense_parts_keep_keyboard_targets_and_full_export_after_focusing(self):
        from playwright.sync_api import expect
        state = oracle_state()
        state.update(material_status='current', history=[], bindings=[])
        for r in state['records']:
            r.update(anchor=r['record_id'], sections=[dict(section_id=r['record_id'], text=r['text'], locator={})])
        for o in state['opinions']:
            o['interpretation'] = '合成观点'
            for f in o['facets']:
                for item in f['outside']:
                    item.update(evidence=[], reason='合成范围依据')
        for relation in state['relations']:
            relation.update(evidence=[])
        state['themes'][1]['label'] = '样本来源'
        parts = state['a_reference']['parts']
        items = state['a_reference']['items']
        part, item = parts[0], items[0]
        for number in range(15-len(parts)):
            ident = 'dense-'+str(number)
            parts.append(dict(id=ident, label='合成第'+str(number)+'部分：'+'来源范围风险条件和限定'*5))
            items.append(dict(item, id='item-'+ident, part_id=ident, text='完整条文 '+ident))
        part['label'] = '数据与方法：'+'来源与限定条文'*6
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
            path = Path(folder)/'dense.html'
            path.write_text(render(state), encoding='utf-8')
            browser = pw.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport={'width': 1366, 'height': 768})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(path.as_uri())
            chart = page.locator('#attention-map')
            for width in (1366, 320):
                page.set_viewport_size({'width': width, 'height': 768})
                expect(chart).to_contain_text('15 个部分')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                bounds = chart.locator('svg').evaluate("""(svg) => {
                    const width = svg.viewBox.baseVal.width;
                    return [...svg.querySelectorAll('text')].every(t => {
                        const r = t.getBBox(); return r.x >= 0 && r.x + r.width <= width + 1;
                    });
                }""")
                self.assertTrue(bounds, f'SVG text clips at {width}px')
                self.assertEqual(svg_text_collisions(chart), [], f'SVG labels overlap at {width}px')
                evidence = os.environ.get('ATTENTION_POSITION_EVIDENCE_DIR')
                if evidence:
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(evidence)/f'positions-dense-{width}.png'))
            pick = page.locator('#map-part-select')
            pick.focus()
            pick.select_option('part:P1')
            expect(pick).to_be_focused()
            expect(page.locator('#map-scope')).to_contain_text('数据与方法')
            expect(page.locator('#position-drill summary').filter(has_text='完整条文 dense-0')).to_have_count(0)
            mark = chart.locator('[data-map-record="r2"][data-map-region="part:P1"]')
            mark.press('Enter')
            expect(mark).to_be_focused()
            expect(chart.locator('[data-map-record="r2"][aria-current="true"]').first).to_be_visible()
            toggle = page.locator('#map-a-toggle')
            toggle.press('Space')
            expect(toggle).not_to_be_checked()
            expect(toggle).to_be_focused()
            toggle.press('Space')
            expect(toggle).to_be_checked()
            theme = page.locator('#map-theme-select')
            theme.focus()
            theme.select_option('T1')
            expect(theme).to_be_focused()
            expect(page.locator('#map-scope')).to_contain_text('视图聚焦')
            with page.expect_download() as download:
                page.get_by_role('button', name='导出 SVG', exact=True).click()
            exported = Path(download.value.path()).read_text(encoding='utf-8')
            self.assertIn('15 个部分', exported)
            self.assertIn('完整条文 dense-', exported)
            self.assertIn('当前筛选 · 分母 4', exported)
            self.assertEqual(errors, [])
            browser.close()

    def test_focus_distribution_opens_positions_and_marks_all_selected_record_regions(self):
        from playwright.sync_api import expect
        state = oracle_state()
        state.update(material_status='current', history=[], relations=[])
        state['themes'] = []
        for r in state['records']:
            r.update(anchor=r['record_id'], sections=[dict(section_id=r['record_id'], text=r['text'], locator={})])
        for o in state['opinions']:
            o['interpretation'] = '合成观点'
            for f in o['facets']:
                f['themes'] = []
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
            path = Path(folder) / 'positions.html'
            path.write_text(render(state), encoding='utf-8')
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport={'width': 1440, 'height': 1000})
            page.goto(path.as_uri())
            page.get_by_role('button', name='关注分布', exact=True).click()
            expect(page.locator('#view-positions')).to_be_visible()
            before = page.locator('#view-version').inner_text()
            self.assertIn('3/4 条记录', page.locator('#view-positions > p').first.inner_text())
            selected = page.locator('#view-positions [data-position-region][aria-current="true"]')
            self.assertEqual(set(selected.evaluate_all('(es)=>es.map(e=>e.dataset.positionRegion)')),
                {'part:P1', 'part:P2'})
            for fid in ('f1', 'f2'):
                self.assertGreater(page.locator('#view-positions a[aria-current="true"][href="#view-facet-'+fid+'"]').count(), 0)
            output = os.environ.get('ATTENTION_REVIEW_FIX_EVIDENCE_DIR')
            if output:
                Path(output).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(output) / 'focus-distribution-1440.png'), full_page=True)
            select_reading_record(page, 1)
            self.assertEqual(set(selected.evaluate_all('(es)=>es.map(e=>e.dataset.positionRegion)')),
                {'part:P1', 'part:P2'})
            expect(page.locator('#view-positions a[aria-current="true"][href="#view-facet-f1"]')).to_have_count(0)
            expect(page.locator('#view-positions a[aria-current="true"][href="#view-facet-f3"]')).not_to_have_count(0)
            self.assertEqual(page.locator('#view-version').inner_text(), before)
            self.assertIn('3/4 条记录', page.locator('#view-positions > p').first.inner_text())
            select_reading_record(page, 2)
            self.assertEqual(set(selected.evaluate_all('(es)=>es.map(e=>e.dataset.positionRegion)')),
                {'part:P1', 'outside', 'pending', 'disposition'})
            page.set_viewport_size({'width': 420, 'height': 1000})
            self.assertEqual(set(selected.evaluate_all('(es)=>es.map(e=>e.dataset.positionRegion)')),
                {'part:P1', 'outside', 'pending', 'disposition'})
            if output:
                page.screenshot(path=str(Path(output) / 'focus-distribution-420.png'), full_page=True)
            select_reading_record(page, 3)
            self.assertEqual(set(selected.evaluate_all('(es)=>es.map(e=>e.dataset.positionRegion)')), {'unprocessed'})
            self.assertEqual(page.locator('#view-version').inner_text(), before)
            open_panel(page, 'view-filters')
            page.locator('#view-record').select_option('r4')
            self.assertIn('0/1 条记录', page.locator('#view-positions > p').first.inner_text())
            self.assertEqual(set(selected.evaluate_all('(es)=>es.map(e=>e.dataset.positionRegion)')), {'unprocessed'})
            browser.close()

    def test_pending_suggestion_retains_target_without_becoming_confirmed_coverage(self):
        state = oracle_state()
        state['opinions'][0]['facets'][0]['status'] = 'needs_review'
        summary = summarize(state)
        before = copy.deepcopy(summary)
        positions = project_positions(summary)
        entries = [p for p in positions['placements'] if p['facet_id'] == 'f1']
        self.assertEqual({p['region_id'] for p in entries}, {'item:A1', 'item:A2', 'pending'})
        self.assertTrue(all(p['review_status'] == 'needs_review' for p in entries))
        self.assertEqual(summary['a_parts']['P1']['explicit']['record_ids'], ['r2'])
        self.assertEqual(summary, before)

    def test_no_a_stale_targets_and_invalidation_never_look_current(self):
        state = oracle_state()
        state['a_reference']['items'] = []
        absent = project_positions(summarize(state))
        self.assertEqual({p['region_id'] for p in absent['placements']}, {'absent', 'disposition'})
        for invalidation in ('version', 'missing', 'a_source', 'b_source', 'legacy_source'):
            with self.subTest(invalidation=invalidation):
                state = oracle_state()
                link = state['opinions'][0]['facets'][0]['a_links'][0]
                if invalidation == 'version':
                    link['version'] = 'old'
                elif invalidation == 'missing':
                    link['a_item_id'] = 'removed'
                elif invalidation == 'legacy_source':
                    state['material_status'] = 'needs_revalidation'
                else:
                    state['a_material_status' if invalidation == 'a_source' else 'b_material_status'] = 'needs_revalidation'
                projected = project_positions(summarize(state))
                entries = [p for p in projected['placements'] if p['facet_id'] == 'f1']
                self.assertTrue(any(p['region_id'] == 'stale' for p in entries))
                self.assertFalse(any(p['region_id'] == 'item:A1' for p in entries))

    def test_browser_region_drilldown_filters_and_source_editor(self):
        state = oracle_state()
        state.update(material_status='current', history=[])
        for r in state['records']:
            r.update(anchor=r['record_id'], sections=[dict(section_id=r['record_id'], text=r['text'], locator={})])
        state['opinions'][0]['facets'][0]['evidence'] = [dict(source_id='synthetic-source', section_id='r1', start=0, end=4, quote='合成原话')]
        state['opinions'][0]['facets'][0]['qualifiers'] = dict(conditions='若有记录才补充')
        for o in state['opinions']:
            o['interpretation'] = '合成观点'
            for f in o['facets']:
                for t in f['themes']:
                    t['reason'] = '合成依据'
        for o in state['opinions']:
            for f in o['facets']:
                for a in f.get('outside', []):
                    a.update(evidence=[], reason='合成清单外依据')
        for relation in state['relations']:
            relation.update(evidence=[], direction='条件方向', reading='合成读法', ambiguity='待核')
            for endpoint in relation['endpoints']:
                endpoint['role'] = '合成角色'
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
            path = Path(folder) / 'positions.html'
            path.write_text(render(state), encoding='utf-8')
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(path.as_uri())
            open_panel(page, 'view-a-positions')
            open_panel(page, 'view-filters')
            region = page.locator('#view-positions')
            self.assertEqual(errors, [])
            self.assertIn('B关注分布', region.inner_text())
            point = page.locator('#attention-map a[href="#view-facet-f1"]').first
            point.focus(); page.keyboard.press('Enter')
            self.assertIn('合成原话', page.locator('#focus-reading').inner_text())
            self.assertIn('若有记录才补充', page.locator('#focus-reading').inner_text())
            self.assertLess(page.locator('#focus-reading').bounding_box()['y'], 768)
            page.get_by_role('button', name='修改解释', exact=True).click()
            self.assertEqual(page.locator('#facet').input_value(), 'f1')
            page.locator('#interpretation').fill('未暂存的文字')
            open_panel(page, 'view-record-r1')
            page.get_by_role('button', name='查看原话并修改').nth(1).click()
            self.assertEqual(page.locator('#facet').input_value(), 'f2')
            self.assertEqual(page.locator('#interpretation').input_value(), '合成解释')
            page.get_by_role('button', name='查看原话并修改').first.click()
            self.assertEqual(page.locator('#facet').input_value(), 'f1')
            self.assertEqual(page.locator('#interpretation').input_value(), '未暂存的文字')
            self.assertEqual(page.evaluate('JSON.parse(document.getElementById("attention-data").textContent).revision'), 7)
            page.evaluate("AttentionPositions.setOverlay({analysis_id:'synthetic',base_revision:7,a_version:'synthetic-A',label:'合成候选',placements:[{label:'候选条件',region_id:'item:A1'}]})")
            self.assertIn('尚未保存，全部待核', region.inner_text())
            with self.assertRaises(Exception):
                page.evaluate("AttentionPositions.setOverlay({analysis_id:'wrong',base_revision:7,a_version:'synthetic-A',placements:[]})")
            page.locator('#view-boiler').select_option('true')
            self.assertIn('1/4', page.locator('#view-positions > p').first.inner_text())
            for width in (1440, 420):
                page.set_viewport_size({'width': width, 'height': 1000})
                region.scroll_into_view_if_needed()
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                output = os.environ.get('ATTENTION_POSITION_EVIDENCE_DIR')
                if output:
                    Path(output).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(output) / f'positions-{width}.png'))
            self.assertEqual(errors, [])
            large = copy.deepcopy(state)
            for index in range(45):
                record = copy.deepcopy(state['records'][0])
                record.update(record_id='new-B-' + str(index), anchor='new-B-' + str(index))
                large['records'].append(record)
                opinion = copy.deepcopy(state['opinions'][0])
                opinion.update(record_id=record['record_id'], opinion_id='new-opinion-' + str(index))
                opinion['facets'] = opinion['facets'][:1]
                opinion['facets'][0]['facet_id'] = 'new-facet-' + str(index)
                large['opinions'].append(opinion)
            path.write_text(render(large), encoding='utf-8')
            page.goto(path.as_uri())
            open_panel(page, 'view-a-positions')
            open_panel(page, 'view-filters')
            self.assertIn('48/49', page.locator('#view-positions > p').first.inner_text())
            self.assertEqual(page.locator('#attention-map [data-map-theme="T1"] [data-map-region="part:P1"]').count(), 8)
            page.locator('#attention-map a[aria-label="T1 · 展开全部 47 条记录"]').click()
            page.locator('.focus-cluster-records > summary').click()
            self.assertEqual(page.locator('.focus-cluster-records button').count(),47)
            with page.expect_download() as download:
                page.get_by_role('button', name='导出 SVG', exact=True).click()
            exported = Path(download.value.path()).read_text(encoding='utf-8')
            self.assertIn('new-B-44', exported)
            self.assertIn('分母 49', exported)
            self.assertEqual(errors, [])
            browser.close()
