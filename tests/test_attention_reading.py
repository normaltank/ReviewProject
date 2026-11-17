"""Read, trace and correct synthetic results through the ordinary offline page."""
import os
import copy
import json
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from reviewproto.attention_candidate_ui import CandidateSession
from reviewproto.attention_candidates import ReplayProvider
from reviewproto.desktop import Controller
from test_attention_candidate_ui import prepare


class AttentionReading(unittest.TestCase):
    def test_saved_reading_shows_b_and_multiple_a_matches_before_opening_evidence(self):
        from reviewproto.attention import AttentionWorkspace
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            pack = Path(tmp) / 'pack'
            with closing(AttentionWorkspace(pack)) as ws:
                state = ws.build(dict(schema='attention-input/1', records=[dict(anchor='合成记录',
                    text='若有记录，请标明图例。', visibility='author_visible',
                    scores=[dict(label='原分', raw_value=' 7 / 9 ')])],
                    a_reference=dict(version='v1', items=[dict(id=k, text=t, locator='合成') for k,t in
                        [('a', '说明图例含义'), ('b', '说明记录来源')]])))
                record = state['records'][0]
                ev = dict(source_id=record['source_id'], section_id='合成记录', start=0, end=12,
                    quote='若有记录，请标明图例。')
                ev['end'] = len(ev['quote'])
                ws.apply(dict(schema='attention-patch/2', analysis_id=state['analysis_id'], base_revision=0,
                    actor='合成核对者', reason='核对对应', edits=[dict(opinion_id='o', record_id=record['record_id'],
                    interpretation='补充图例', status='working', facets=[dict(facet_id='f', interpretation='标明图例',
                    status='working', evidence=[ev], a_links=[dict(a_item_id=k, version='v1', kind='partial',
                    status='working', scope='图例说明', reason='只对应说明范围', evidence=[ev]) for k in ('a','b')])])]))
                ws.recover()
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport=dict(width=420, height=1000))
            page.goto((pack / 'attention.html').as_uri())
            visible = page.locator('#view-detail').inner_text()
            for text in ('标明图例', '说明图例含义', '说明记录来源', '部分对应'):
                self.assertIn(text, visible)
            self.assertNotIn('若有记录，请标明图例。', visible)
            self.assertNotIn('7 / 9', visible)
            self.assertNotIn('working', visible)
            self.assertFalse(page.locator('#page-draft').is_visible())
            page.locator('#view-detail > details > summary').first.click()
            self.assertIn('若有记录，请标明图例。', page.locator('#view-detail').inner_text())
            self.assertIn(' 7 / 9 ', page.locator('#view-detail').text_content())
            page.get_by_role('button', name='查看原话并修改').click()
            page.locator('#interpretation').fill('标明图例并说明含义')
            page.locator('#stage').click()
            self.assertTrue(page.locator('#download').is_enabled(), 'Ordinary edits do not require audit form knowledge')
            self.assertIn('尚未保存的修改', page.locator('#page-draft').inner_text())
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 420)
            browser.close()

    def test_a_replacement_pending_scopes_remain_visible_and_follow_saved_filters(self):
        from reviewproto.attention import AttentionWorkspace
        from attention_browser import open_panel
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            root = Path(tmp); pack = root / 'pack'
            with closing(AttentionWorkspace(pack)) as ws:
                saved = ws.build({'schema': 'attention-input/1', 'records': [dict(
                    anchor=anchor, text='可以说明样本。', visibility='author_visible', paper_id=group)
                    for anchor, group in [('甲', '材料甲'), ('乙', '材料乙')]],
                    'a_reference': dict(version='v1', items=[dict(id=k, text=t, locator='合成') for k,t in [('a','旧版样本范围说明' + '（保留原有范围，不依据新版扩充说明）' * 3), ('b','旧版记录来源说明')]])})
                record = saved['records'][0]
                ev = dict(source_id=record['source_id'], section_id='甲', start=0, end=7, quote='可以说明样本。')
                facet = dict(facet_id='f', interpretation='说明样本', status='working', evidence=[ev],
                    expression=dict(function='具体建议', boilerplate_candidate=False), a_links=[dict(a_item_id=k, version='v1', kind='partial',
                    scope='样本', reason='仅样本说明', evidence=[ev], status='working') for k in ('a', 'b')],
                    outside=[dict(scope='其他范围', reason='未列入清单', evidence=[ev], status='working')])
                opinion = dict(opinion_id='o', record_id=record['record_id'], interpretation='说明样本', status='working', facets=[facet])
                def saved_opinion():
                    source = ws.state()['opinions'][0]
                    return {key: copy.deepcopy(source[key]) for key in
                        ('opinion_id', 'record_id', 'interpretation', 'status', 'facets', 'replaces')}
                def apply():
                    ws.apply(dict(schema='attention-patch/2', analysis_id=saved['analysis_id'], base_revision=ws.state()['revision'],
                        actor='合成核对者', reason='核对范围', edits=[opinion]))
                    ws.recover()
                apply()
                browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
                page = browser.new_page(offline=True, viewport={'width': 420, 'height': 1000})
                def view(expected_a, expected_outside, denominator=2):
                    header = page.locator('#view-version')
                    self.assertTrue(header.is_visible())
                    self.assertNotIn('B解释', header.inner_text())
                    for label, count in [('A对应', expected_a), ('清单外范围', expected_outside)]:
                        if count:
                            self.assertIn(f'{label} {count} 项', header.inner_text())
                        else:
                            self.assertNotIn(label, header.inner_text())
                    self.assertIn(f'当前范围 {denominator} 条记录（分母）', header.inner_text())
                page.goto((pack / 'attention.html').as_uri())
                source = root / 'new-a.json'
                source.write_text(json.dumps(dict(schema='attention-a-input/1', a_reference=dict(version='v2',
                    items=[dict(id='a', text='可以说明样本范围', locator='新合成')]))), encoding='utf-8')
                ws.import_a(source, actor='合成核对者', reason='显式换版'); current = ws.recover()
                self.assertEqual(current['opinions'][0]['facets'][0]['status'], 'working')
                self.assertTrue(all(link['status'] == 'needs_review' for link in
                    current['opinions'][0]['facets'][0]['a_links'] + current['opinions'][0]['facets'][0]['outside']))
                page.reload(); view(1, 1)  # two A links, one facet; overlap is not summed
                # Both a reused ID and a deleted ID retain their original version's text.
                first_read = page.locator('#view-detail').inner_text()
                for title in ('旧版样本范围说明', '旧版记录来源说明', '旧版 v1'):
                    self.assertIn(title, first_read)
                self.assertNotIn('可以说明样本范围', first_read)
                self.assertEqual(first_read.count('旧版 v1'), 2)
                page.locator('[id="view-record-' + record['record_id'] + '"] > summary').click()
                page.locator('#view-facet-f .facet-a > summary').click()
                saved_links = page.locator('#view-facet-f .facet-a p').filter(has_text='保存的对应').all_text_contents()
                self.assertEqual(len(saved_links), 2)
                self.assertIn('旧版样本范围说明', saved_links[0])
                self.assertIn('旧版记录来源说明', saved_links[1])
                self.assertTrue(all('旧版 v1' in text for text in saved_links))
                self.assertNotIn('可以说明样本范围', ' '.join(saved_links))
                page.reload()
                self.assertTrue(all(page.locator('#' + key).get_attribute('open') is None
                    for key in ('view-statistics', 'view-a-positions', 'attention-editor', 'reading-history')))
                # A B correction also keeps the old destinations pending, while
                # the facet itself remains a working interpretation.
                opinion = saved_opinion()
                opinion['facets'][0]['interpretation'] = '仅说明样本'
                apply(); page.reload(); view(1, 1)
                output = os.environ.get('ATTENTION_READING_FIX_EVIDENCE_DIR')
                if output:
                    for width in (420, 1440):
                        page.set_viewport_size(dict(width=width, height=1000))
                        page.screenshot(path=str(Path(output) / f'a-pending-{width}.png'))
                open_panel(page, 'view-filters')
                page.locator('#view-record').select_option(current['records'][1]['record_id']); view(0, 0, 1)
                page.locator('#view-record').select_option('*')
                page.locator('#view-paper').select_option(json.dumps('材料甲', ensure_ascii=False)); view(1, 1, 1)
                page.locator('#view-paper').select_option('*')
                page.locator('#view-boiler').select_option('true'); view(0, 0)
                page.get_by_role('button', name='清除筛选').click(); view(1, 1)
                # Only the removed A item remains: pending comes from the
                # summary's unassigned range, not a current A item column.
                opinion = saved_opinion()
                opinion['facets'][0]['a_links'] = [link for link in opinion['facets'][0]['a_links'] if link['a_item_id'] == 'b']
                apply(); page.reload(); view(1, 1)
                # Withdrawn destinations stay excluded by the existing summary.
                opinion = saved_opinion()
                for link in opinion['facets'][0]['a_links'] + opinion['facets'][0]['outside']:
                    link['status'] = 'withdrawn'
                apply(); page.reload(); view(0, 0)
                browser.close()

    def test_candidate_snapshot_can_collapse_without_hiding_unstaged_changes(self):
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            pack = Path(tmp) / 'pack'
            _, response = prepare(pack)
            session = CandidateSession(pack)
            session.generate('synthetic-draft', ReplayProvider([response]))
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True)
            page.on('dialog', lambda d: d.accept())
            page.goto(session.preview('synthetic-draft').as_uri())
            page.locator('#candidate-saved > summary').click()
            page.locator('#attention-editor > summary').click()
            page.locator('#interpretation').fill('尚未暂存的合成编辑')
            page.locator('#candidate-saved > summary').click()
            self.assertTrue(page.locator('#page-draft').is_visible())
            self.assertIn('未暂存', page.locator('#page-draft').inner_text())
            page.locator('#candidate-saved > summary').click()
            self.assertEqual(page.locator('#interpretation').input_value(), '尚未暂存的合成编辑')
            browser.close()

    def test_partial_stale_history_and_unknown_requests_stay_visible_before_details(self):
        from reviewproto.attention_candidate_render import render_candidate_preview
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            pack = Path(tmp) / 'pack'
            _, response = prepare(pack)
            session = CandidateSession(pack)
            run = session.generate('synthetic-history', ReplayProvider([response]))
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, viewport={'width': 420, 'height': 1000})
            for legacy in (False, True):
                with self.subTest(legacy=legacy):
                    shown = copy.deepcopy(run)
                    shown.update(status='running' if legacy else 'partial', validity='needs_revalidation', accepted_revision=1)
                    shown['coverage'][0]['status'] = 'partial'
                    shown['unprocessed'] = [dict(record_id=run['record_ids'][0], section_id='s', reason='synthetic incomplete range')]
                    shown['calls'] = [dict(purpose='format_repair', status='pending')] if legacy else [
                        dict(purpose='analysis', status='in_flight', attempted=True)]
                    shown.pop('request_count', None); shown.pop('format_repair_count', None)
                    path = Path(tmp) / ('legacy.html' if legacy else 'partial.html')
                    path.write_text(render_candidate_preview(shown), encoding='utf-8')
                    page.goto(path.as_uri())
                    visible = page.locator('#candidate-preview').inner_text()
                    for text in ('已在修订 1 保存', '部分处理 1 条', '未完成范围 1 项', '须重新生成', '请求结果与用量未知'):
                        self.assertIn(text, visible)
                    self.assertNotIn('synthetic-history', visible, 'Long run identity belongs to provenance')
                    self.assertFalse(page.locator('#candidate-audit').evaluate('(e)=>e.open'))
                    page.get_by_role('link', name='查看处理明细', exact=True).focus()
                    page.keyboard.press('Enter')
                    audit = page.locator('#candidate-audit').inner_text()
                    self.assertIn('未完成：s', audit)
                    self.assertIn('尝试：未知' if legacy else '尝试：1', audit)
                    source_id = 'candidate-source-' + run['record_ids'][0]
                    # Opening the original source from a copied deep link also
                    # opens every disclosure ancestor on first document load.
                    page.goto(path.as_uri() + '#' + source_id); page.reload()
                    page.locator('#candidate-sources[open]').wait_for(state='visible', timeout=10000)
                    page.locator('#' + source_id + '[open]').wait_for(state='visible', timeout=10000)
                    self.assertTrue(page.locator('#candidate-sources').evaluate('(e)=>e.open'))
                    self.assertTrue(page.locator('#' + source_id).evaluate('(e)=>e.open'))
                    self.assertIn('若有记录，请标明图例。', page.locator('#' + source_id).inner_text())
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 420)
            browser.close()

    def test_read_evidence_correct_download_and_reopen_saved_revision(self):
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            pack = Path(tmp) / 'pack'
            _, response = prepare(pack)
            session = CandidateSession(pack)
            session.generate('synthetic-reading', ReplayProvider([response]))
            preview = session.preview('synthetic-reading')
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            page = browser.new_page(offline=True, accept_downloads=True, viewport={'width': 1440, 'height': 1000})
            errors, requests = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: requests.append(r.url) if r.url.startswith(('http:', 'https:')) else None)
            page.on('dialog', lambda d: d.accept())
            page.goto(preview.as_uri())
            candidate = page.locator('[id^="candidate-facet-"]').first
            self.assertLess(candidate.bounding_box()['y'], 700, 'Read B before engineering diagnostics')
            self.assertIn('标明图例', candidate.inner_text())
            self.assertIn('结果尚未保存', page.locator('#candidate-preview').inner_text())
            self.assertIn('工程回放（非实际推理）', page.locator('#candidate-preview').inner_text())
            self.assertFalse(page.locator('#candidate-audit').evaluate('(e)=>e.open'))
            page.get_by_role('link', name='查看分布图', exact=True).click()
            self.assertTrue(page.locator('#candidate-position-overlay').is_visible())
            page.locator('#view-filters > summary').click()
            page.locator('#view-boiler').select_option('true')
            self.assertIn('没有候选位置', page.locator('#candidate-position-overlay').inner_text())
            self.assertFalse(page.locator('#candidate-saved').evaluate('(e)=>e.open'))
            page.locator('#view-boiler').select_option('*')
            page.locator('#view-filters > summary').click()
            candidate.locator('summary').first.focus()
            page.keyboard.press('Enter')
            self.assertIn('条件：若有记录', candidate.inner_text())
            candidate.get_by_role('link', name='查看本条完整原话与原分').click()
            self.assertIn('若有记录，请标明图例。', page.locator('[id^="candidate-source-"]').inner_text())
            self.assertTrue(page.locator('[id^="candidate-source-"]').evaluate('(e)=>e.open'))
            saved = session.accept('synthetic-reading', actor='合成核对者', reason='接收待核')
            fid = saved['opinions'][0]['facets'][0]['facet_id']
            controller = Controller(); controller.open_attention(pack)
            page.goto((pack / 'attention.html').as_uri())
            self.assertFalse(page.locator('#attention-editor').evaluate('(e)=>e.open'))
            self.assertIn('标明图例', page.locator('#view-detail').inner_text())
            page.locator('#view-detail > details > summary').first.click()
            self.assertIn('若有记录，请标明图例。', page.locator('#view-detail').inner_text())
            page.get_by_role('button', name='查看原话并修改').first.click()
            self.assertTrue(page.locator('#attention-editor').evaluate('(e)=>e.open'))
            self.assertEqual(page.locator('#facet').input_value(), fid)
            page.locator('#actor').fill('合成核对者'); page.locator('#reason').fill('保留条件')
            page.locator('#interpretation').fill('如有记录才补充图例')
            page.locator('#attention-editor > summary').click()
            self.assertIn('未暂存', page.locator('#page-draft').inner_text())
            page.get_by_role('button', name='查看原话并修改').first.click()
            self.assertEqual(page.locator('#interpretation').input_value(), '如有记录才补充图例')
            self.assertIn('请先暂存修改', page.locator('#message').inner_text())
            page.locator('#stage').click()
            self.assertIn('尚未保存的修改', page.locator('#page-draft').inner_text())
            before = (pack / 'attention-state.json').read_bytes()
            with page.expect_download() as download:
                page.locator('#download').click()
            patch = Path(tmp) / 'draft.json'; download.value.save_as(patch)
            self.assertEqual((pack / 'attention-state.json').read_bytes(), before)
            self.assertIn('尚未保存的修改', page.locator('#page-draft').inner_text())
            self.assertIn('已保存修订 1', page.locator('#revision').inner_text())
            self.assertIn('标明图例', page.locator('#view-detail').inner_text())
            self.assertEqual(controller.apply_attention(patch)['revision'], 2)
            self.assertEqual(controller.recover_attention()['revision'], 2)
            page.goto((pack / 'attention.html').as_uri() + '#view-facet-' + fid)
            page.reload()
            self.assertTrue(page.locator('#view-detail > details').first.evaluate('(e)=>e.open'))
            self.assertIn('如有记录才补充图例', page.locator('#view-detail').inner_text())
            self.assertIn('已保存修订 2', page.locator('#revision').inner_text())
            self.assertEqual(page.locator('#page-draft').text_content(), '')
            self.assertEqual(errors, []); self.assertEqual(requests, [])
            browser.close()
