"""Material groups travel from ordinary input through saved filters and details."""
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_input import AttentionInput
from reviewproto.attention_summary import summarize
from reviewproto.desktop import Controller


class AttentionInputGroups(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def ordinary_package(self):
        draft = AttentionInput()
        for anchor, group in [('甲一', '材料甲'), ('甲二', '材料甲'), ('乙', '材料乙'), ('未知', '')]:
            draft.add_transcription(anchor, anchor + '合成原话😀', 'visibility_unknown', [], anchor + '位置', group)
        path = self.root / 'ordinary'
        Controller().build_prepared_attention(draft, path)
        with closing(AttentionWorkspace(path)) as ws:
            return path, ws.state()

    def test_controller_groups_filter_saved_record_sets_including_unknown(self):
        path, state = self.ordinary_package()
        for group, anchors in [('材料甲', {'甲一', '甲二'}), ('材料乙', {'乙'}), (None, {'未知'})]:
            with self.subTest(group=group):
                summary = summarize(state, {'paper_ids': [group]})
                self.assertEqual(summary['denominator']['count'], len(anchors))
                self.assertEqual({d['record']['anchor'] for d in summary['details'].values()}, anchors)
        self.assertEqual(summarize(state, {'paper_ids': ['材料甲', '材料乙']})['denominator']['count'], 3)

    def test_declared_group_precedes_legacy_locator_but_locator_only_still_filters(self):
        source = self.root / 'legacy.json'
        source.write_text(json.dumps({'schema': 'attention-input/1', 'a_reference': {'version': 'none', 'items': []},
            'records': [dict(anchor='显式', text='显式合成原话', visibility='author_visible', paper_id='显式材料', locator={'paper_id': '旧定位值'}),
                        dict(anchor='旧输入', text='旧输入原话', visibility='author_visible', locator={'paper_id': '旧材料'}),
                        dict(anchor='未声明', text='未声明原话', visibility='author_visible')]}), encoding='utf-8')
        path = self.root / 'legacy'
        Controller().build_attention(source, path)
        with closing(AttentionWorkspace(path)) as ws:
            state = ws.state()
        for group, count in [('显式材料', 1), ('旧材料', 1), ('旧定位值', 0), (None, 1)]:
            with self.subTest(group=group):
                self.assertEqual(summarize(state, {'paper_ids': [group]})['denominator']['count'], count)

    def test_real_browser_group_picker_filters_and_plain_details_show_declared_groups(self):
        from playwright.sync_api import sync_playwright
        path, state = self.ordinary_package()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            try:
                page = browser.new_page(offline=True)
                page.goto((path / 'attention.html').as_uri())
                choices = page.locator('#view-paper option').all_text_contents()
                self.assertEqual(set(choices), {'全部', '材料甲', '材料乙', '未知材料组'})
                for group, anchors in [('材料甲', {'甲一', '甲二'}), ('材料乙', {'乙'}), (None, {'未知'})]:
                    page.locator('#view-paper').select_option(json.dumps(group, ensure_ascii=False))
                    self.assertEqual(page.locator('#view-detail > details').count(), len(anchors))
                    self.assertIn('0/' + str(len(anchors)), page.locator('#view-hits').inner_text())
                    for detail in page.locator('#view-detail > details').all():
                        detail.locator('summary').click()
                        self.assertIn('材料组：' + (group or '未知'), detail.inner_text())
                context = browser.new_context(java_script_enabled=False, offline=True)
                plain = context.new_page(); plain.goto((path / 'attention.html').as_uri())
                details = plain.locator('.attention-summary > details')
                self.assertEqual(details.count(), 4)
                for detail in details.all(): detail.locator('summary').click()
                self.assertEqual(plain.get_by_text('材料组：材料甲', exact=True).count(), 2)
                self.assertEqual(plain.get_by_text('材料组：材料乙', exact=True).count(), 1)
                self.assertEqual(plain.get_by_text('材料组：未说明', exact=True).count(), 1)
                context.close()
            finally:
                browser.close()
