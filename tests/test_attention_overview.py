import os
import json
import tempfile
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from reviewproto.attention import AttentionWorkspace


class AttentionOverview(unittest.TestCase):
    def test_new_packages_overview_tracks_saved_revision_not_downloaded_draft(self):
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            errors = []
            for count, with_a in [(2, False), (3, True)]:
                ws = AttentionWorkspace(Path(folder) / str(count))
                try:
                    reference = dict(version='new-reference', parts=[], items=[])
                    if with_a:
                        reference.update(parts=[dict(id='opening', label='开题'), dict(id='empty', label='空部分'), dict(id='closure', label='收束')], items=[dict(id=k, part_id=part, text=title, locator='合成逐条录入') for k, part, title in [('anchor', 'opening', '限定表达'), ('zero', 'closure', '边界条件'), ('another', 'closure', '其他方向')]])
                    payload = dict(schema='attention-input/1', records=[dict(anchor=f'fresh-{i}', text=f'新材料{i}：若有证据，可以收束。', visibility='visibility_unknown', scores=[dict(label='自由分栏', raw_value=' 7 / 9 ')] if i == 0 else []) for i in range(count)], a_reference=reference)
                    source = Path(folder) / f'input-{count}.json'
                    original = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                    source.write_bytes(original)
                    ws.build(input_path=source)
                    page = browser.new_page(offline=True, accept_downloads=True)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto((ws.path / 'attention.html').as_uri())
                    overview = page.get_by_role('region', name='当前关注概览')
                    page.get_by_role('link', name='查看当前关注概览与回查集合').focus()
                    page.keyboard.press('Enter')
                    self.assertIn(f'{count} 条记录', overview.inner_text(timeout=1200))
                    self.assertIn('尚未形成有效观点方面', overview.inner_text())
                    self.assertIn('1 项原分', overview.inner_text())
                    if not with_a:
                        self.assertIn('A未导入', overview.inner_text())
                    page.locator('#passage').select_option(index=1)
                    page.locator('#interpretation').fill('收束范围的工作解释')
                    page.locator('#actor').fill('合成核对者')
                    page.locator('#reason').fill('保存观点')
                    page.locator('#stage').click()
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    patch = Path(folder) / f'draft-{count}.json'
                    download.value.save_as(patch)
                    self.assertIn('已保存修订 0', overview.inner_text())
                    self.assertIn('0 个方面', overview.inner_text())
                    ws.apply(input_path=patch)
                    ws.recover()
                    page.reload()
                    self.assertIn('已保存修订 1', overview.inner_text())
                    self.assertIn('1 个观点 / 1 个方面', overview.inner_text())
                    self.assertIn(f'1/{count}', overview.inner_text())
                    target = overview.get_by_role('link', name='fresh-0', exact=True).first
                    href = target.get_attribute('href')
                    target.click()
                    self.assertIn('收束范围的工作解释', page.locator('#view-detail').inner_text())
                    self.assertTrue(page.locator(href).evaluate('(e)=>e.open'))
                    page.locator('#view-record').select_option(ws.state()['records'][1]['record_id'])
                    self.assertIn('1 条记录', overview.inner_text())
                    self.assertIn('0/1', overview.inner_text())
                    source.write_bytes(original + b' ')
                    ws.recover()
                    page.reload()
                    self.assertIn('来源失效', overview.inner_text())
                    self.assertIn('旧快照', overview.inner_text())
                    source.write_bytes(original)
                    ws.recover()
                    page.reload()
                    self.assertNotIn('来源失效', overview.inner_text())
                    self.assertIn('已保存修订 1', overview.inner_text())
                    page.close()
                finally:
                    ws.close()
            self.assertEqual(errors, [])
            browser.close()

    def test_changed_shape_saved_facts_are_readable_without_scripts_and_share_filter_sets(self):
        from reviewproto.attention_render import render
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            errors = []
            for count in (2, 3):
                records = [dict(record_id=f'novel-{i}', anchor=f'新锚点{i}', text=f'新原话{i}', sections=[dict(section_id=f'new-section-{i}', text=f'新原话{i}')], scores=[dict(label='自由原分', raw_value=' 7 / 9 ')] if i == 0 else [], locator={}) for i in range(count)]
                reference = dict(version='different-v9', parts=[dict(id=x, label=x) for x in ('start', 'empty', 'end')], items=[dict(id=x, text=x, part_id=part, locator='新定位') for x, part in [('hit', 'start'), ('zero', 'end'), ('nil', 'end')]]) if count == 3 else dict(version=None, parts=[], items=[])
                opinions = []
                for i in range(2):
                    f = dict(facet_id=f'new-facet-{i}', interpretation=f'全新方面{i}', kind='content', status='working' if i == 0 else 'needs_review', evidence=[], themes=[dict(theme_id='novel-theme', status='working', reason='新成员依据')], a_links=[dict(a_item_id='hit', version='different-v9', kind='explicit', status='working', reason='新关联依据', scope='新范围', evidence=[])] if count == 3 else [], outside=[], qualifiers={}, expression=dict(function='限定建议' if i == 0 else '其他表达'))
                    opinions.append(dict(opinion_id=f'new-opinion-{i}', record_id=f'novel-{i}', interpretation='全新观点', status='working', facets=[f]))
                state = dict(analysis_id='another-analysis', revision=12, rules_version='novel-rules', material_status='current', b_material_status='current', a_material_status='current', history=[], records=records, opinions=opinions, themes=[dict(theme_id='novel-theme', label='新主题边界', definition='新定义', status='working', parent_ids=[])], a_reference=reference, relations=[dict(relation_id='new-scope', type='novel_type', status='working', endpoints=[dict(facet_id=f'new-facet-{i}', role='限定角色') for i in range(2)], scope='只限两方面', reading='新范围读法', direction='未定', ambiguity='保留歧义', evidence=[])])
                path = Path(folder) / f'facts-{count}.html'
                path.write_text(render(state), encoding='utf-8')
                for scripts in (False, True):
                    context = browser.new_context(java_script_enabled=scripts, offline=True, viewport={'width': 420, 'height': 1000})
                    page = context.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(path.as_uri())
                    overview = page.get_by_role('region', name='当前关注概览')
                    self.assertIn('2 个观点 / 2 个方面', overview.inner_text())
                    self.assertIn('1 个主题定义 · 1 个当前关系组', overview.inner_text())
                    self.assertIn(f'2/{count}', overview.inner_text())
                    self.assertNotIn('A五部分', page.content())
                    if count == 3:
                        for title in ('empty', 'zero', 'nil'):
                            self.assertIn(title, page.locator('#view-summary').text_content())
                        self.assertIn('A明确对应记录并集 1/3', overview.inner_text())
                        self.assertIn('A待核对记录并集 1/3', overview.inner_text())
                    if scripts:
                        page.locator('#view-matrix-toggle').check()
                        page.locator('#view-graph-toggle').check()
                        self.assertEqual(page.locator('#view-matrix tbody tr').count(), count)
                        self.assertIn('novel_type', page.locator('#view-graph').text_content())
                        page.locator('#view-function').select_option('限定建议')
                        self.assertIn(f'1/{count}', overview.inner_text())
                        self.assertIn('0 个当前关系组', overview.inner_text())
                        self.assertIn('关系组 0 个', page.locator('#view-graph').inner_text())
                        self.assertEqual(page.locator('#view-matrix tbody tr').count(), count)
                        page.get_by_role('button', name='清除筛选').click()
                        page.locator('#view-record').select_option('novel-0')
                        self.assertIn('1 条记录', overview.inner_text())
                        self.assertIn('1/1', overview.inner_text())
                    else:
                        # Native disclosure remains sufficient to read original evidence.
                        page.locator('#view-summary details').filter(has=page.locator('summary', has_text='novel-0')).last.locator('summary').first.click()
                        self.assertIn('新原话0', page.locator('#view-summary').inner_text())
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 420)
                    evidence = os.environ.get('ATTENTION_OVERVIEW_EVIDENCE_DIR')
                    if evidence:
                        Path(evidence).mkdir(parents=True, exist_ok=True)
                        overview.screenshot(path=str(Path(evidence) / f'overview-{count}-{scripts}-420.png'))
                        page.set_viewport_size({'width': 1440, 'height': 1000})
                        overview.screenshot(path=str(Path(evidence) / f'overview-{count}-{scripts}-1440.png'))
                    context.close()
                state.update(material_status='needs_revalidation', b_material_status='needs_revalidation')
                path.write_text(render(state), encoding='utf-8')
                page = browser.new_page(offline=True)
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(path.as_uri())
                overview = page.get_by_role('region', name='当前关注概览')
                self.assertIn('旧快照', overview.inner_text())
                self.assertIn('恢复原绑定文件', overview.inner_text())
                if count == 3:
                    self.assertIn('A明确对应记录并集 0/3', overview.inner_text())
                    self.assertIn('A待核对记录并集 2/3', overview.inner_text())
                page.close()
            self.assertEqual(errors, [])
            browser.close()
