"""Read, trace and correct synthetic results through the ordinary offline page."""
import os
import copy
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from reviewproto.attention_candidate_ui import CandidateSession
from reviewproto.attention_candidates import ReplayProvider
from reviewproto.desktop import Controller
from test_attention_candidate_ui import prepare


class AttentionReading(unittest.TestCase):
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
            page.locator('#interpretation').fill('尚未加入草稿的合成编辑')
            page.locator('#candidate-saved > summary').click()
            self.assertTrue(page.locator('#page-draft').is_visible())
            self.assertIn('未加入草稿', page.locator('#page-draft').inner_text())
            page.locator('#candidate-saved > summary').click()
            self.assertEqual(page.locator('#interpretation').input_value(), '尚未加入草稿的合成编辑')
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
                    for text in ('已在修订 1 接收', '部分处理 1 条', '未完成范围 1 项', '须重新生成', '请求结果与用量未知'):
                        self.assertIn(text, visible)
                    self.assertNotIn('synthetic-history', visible, 'Long run identity belongs to provenance')
                    self.assertFalse(page.locator('#candidate-audit').evaluate('(e)=>e.open'))
                    page.get_by_role('link', name='处理范围与运行明细', exact=True).focus()
                    page.keyboard.press('Enter')
                    audit = page.locator('#candidate-audit').inner_text()
                    self.assertIn('未完成：s', audit)
                    self.assertIn('尝试：未知' if legacy else '尝试：1', audit)
                    source_id = 'candidate-source-' + run['record_ids'][0]
                    # Opening the original source from a copied deep link also
                    # opens every disclosure ancestor on first document load.
                    page.goto(path.as_uri() + '#' + source_id); page.reload()
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
            self.assertIn('尚未接收', page.locator('#candidate-preview').inner_text())
            self.assertFalse(page.locator('#candidate-audit').evaluate('(e)=>e.open'))
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
            page.get_by_role('button', name='在原话与编辑区核对').first.click()
            self.assertTrue(page.locator('#attention-editor').evaluate('(e)=>e.open'))
            self.assertEqual(page.locator('#facet').input_value(), fid)
            page.locator('#actor').fill('合成核对者'); page.locator('#reason').fill('保留条件')
            page.locator('#interpretation').fill('如有记录才补充图例')
            page.locator('#attention-editor > summary').click()
            self.assertIn('未加入草稿', page.locator('#page-draft').inner_text())
            page.get_by_role('button', name='在原话与编辑区核对').first.click()
            self.assertEqual(page.locator('#interpretation').input_value(), '如有记录才补充图例')
            self.assertIn('请先加入草稿', page.locator('#message').inner_text())
            page.locator('#stage').click()
            self.assertIn('未应用草稿', page.locator('#page-draft').inner_text())
            before = (pack / 'attention-state.json').read_bytes()
            with page.expect_download() as download:
                page.locator('#download').click()
            patch = Path(tmp) / 'draft.json'; download.value.save_as(patch)
            self.assertEqual((pack / 'attention-state.json').read_bytes(), before)
            self.assertIn('未应用草稿', page.locator('#page-draft').inner_text())
            self.assertIn('已保存修订 1', page.locator('#revision').inner_text())
            self.assertIn('标明图例', page.locator('#view-detail').inner_text())
            self.assertEqual(controller.apply_attention(patch)['revision'], 2)
            self.assertEqual(controller.recover_attention()['revision'], 2)
            page.goto((pack / 'attention.html').as_uri() + '#view-facet-' + fid)
            page.reload()
            self.assertTrue(page.locator('#view-detail > details').first.evaluate('(e)=>e.open'))
            self.assertIn('如有记录才补充图例', page.locator('#view-detail').inner_text())
            self.assertIn('已保存修订 2', page.locator('#revision').inner_text())
            self.assertIn('没有未应用草稿', page.locator('#page-draft').inner_text())
            self.assertEqual(errors, []); self.assertEqual(requests, [])
            browser.close()
