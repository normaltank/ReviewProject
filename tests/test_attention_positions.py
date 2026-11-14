"""Saved-position behavior, using the independent four-record oracle."""
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


class Positions(unittest.TestCase):
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
            region = page.locator('#view-positions')
            self.assertEqual(errors, [])
            self.assertIn('B关注位置', region.inner_text())
            page.locator('[data-position-region="item:A1"]').click()
            self.assertIn('3/4', page.locator('#position-drill').inner_text())
            page.locator('#position-drill a').first.click()
            self.assertTrue(page.locator('#view-record-r1').evaluate('(e)=>e.open'))
            self.assertIn('合成原话', page.locator('#view-facet-f1').inner_text())
            self.assertIn('若有记录才补充', page.locator('#view-facet-f1').inner_text())
            page.get_by_role('button', name='在原话与编辑区核对').first.click()
            self.assertEqual(page.locator('#facet').input_value(), 'f1')
            page.locator('#interpretation').fill('未加入草稿的文字')
            page.get_by_role('button', name='在原话与编辑区核对').nth(1).click()
            self.assertEqual(page.locator('#interpretation').input_value(), '未加入草稿的文字')
            self.assertIn('请先加入草稿', page.locator('#message').inner_text())
            self.assertEqual(page.locator('#facet').input_value(), 'f1')
            self.assertEqual(page.evaluate('JSON.parse(document.getElementById("attention-data").textContent).revision'), 7)
            page.evaluate("AttentionPositions.setOverlay({analysis_id:'synthetic',base_revision:7,a_version:'synthetic-A',label:'合成候选',placements:[{label:'候选条件',region_id:'item:A1'}]})")
            self.assertIn('未接收、全部待核', region.inner_text())
            with self.assertRaises(Exception):
                page.evaluate("AttentionPositions.setOverlay({analysis_id:'wrong',base_revision:7,a_version:'synthetic-A',placements:[]})")
            page.locator('#view-boiler').select_option('true')
            self.assertIn('1/4', page.locator('#position-drill').inner_text())
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
            page.locator('[data-position-region="item:A1"]').click()
            self.assertIn('48/49', page.locator('#position-drill').inner_text())
            self.assertEqual(page.locator('#position-drill li').count(), 20)
            self.assertLessEqual(page.locator('#view-positions svg rect').count(), 12)
            page.get_by_role('button', name='下一页', exact=True).click()
            self.assertIn('显示 21–40 / 48', page.locator('#position-drill').inner_text())
            self.assertEqual(errors, [])
            browser.close()

