"""T3 synthetic public CLI and desktop operations; no real model or materials."""
import json
import importlib.util
import os
from pathlib import Path
import unittest

import test_batch_flow as fixture
from reviewproto.desktop import Controller
from reviewproto.core import ReviewError


class BatchDesktopTests(unittest.TestCase):
    setUp = fixture.BatchFlowTests.setUp
    cli = fixture.BatchFlowTests.cli
    read = fixture.BatchFlowTests.read
    build = fixture.BatchFlowTests.build
    patch = fixture.BatchFlowTests.patch
    apply = fixture.BatchFlowTests.apply
    correct_source = fixture.BatchFlowTests.correct_source

    def test_correct_refresh_and_reopen_preserves_saved_decisions(self):
        original = self.build()
        self.apply(self.patch(original))
        saved = self.read()
        self.correct_source()
        self.cli('batch-refresh')
        refreshed = self.read()
        self.assertEqual(refreshed['material_status'], 'current')
        self.assertEqual(refreshed['sources'][0]['candidates'][0]['value']['object'], '资料范围')
        self.assertEqual(refreshed['decisions'][0]['decision_id'], saved['decisions'][0]['decision_id'])
        self.assertEqual(refreshed['decisions'][0]['validity'], 'needs_revalidation')
        self.assertEqual(refreshed['issues'][0]['validity'], 'needs_revalidation')
        self.cli('batch-recover')
        self.assertEqual(self.read(), refreshed)

    def test_desktop_batch_apply_and_source_correction_use_separate_workspaces(self):
        initial = self.build()
        controller = Controller()
        opened = controller.open_batch(self.batch)
        self.assertEqual(opened['batch_id'], initial['batch_id'])
        self.assertIsNone(controller.path)
        decision = self.root / 'desktop-decision.json'
        decision.write_text(json.dumps(self.patch(initial)), encoding='utf-8')
        applied = controller.apply_batch(decision)
        self.assertFalse(applied['idempotent'])
        self.assertTrue(controller.apply_batch(decision)['idempotent'])
        controller.open_batch_source(initial['sources'][0]['source']['source_id'])
        # Windows TEMP may use an 8.3 alias; compare workspace identities.
        self.assertTrue(controller.path.samefile(self.sources[0]))
        self.assertTrue(controller.batch_path.samefile(self.batch))
        self.assertFalse(controller.path.samefile(controller.batch_path))
        self.assertEqual(controller.recover_batch()['revision'], applied['revision'])
        with self.assertRaisesRegex(ReviewError, 'E_BATCH_SOURCE_ID'):
            controller.open_batch_source('unrelated')

    @unittest.skipUnless(fixture.CHROME.is_file() and importlib.util.find_spec('playwright'), 'Chrome and Playwright needed')
    def test_browser_cost_is_explicit_paused_bound_and_identity_free(self):
        from playwright.sync_api import sync_playwright
        state = self.build()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(fixture.CHROME), headless=True)
            page = browser.new_page(offline=True, accept_downloads=True, viewport=dict(width=420, height=900))
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.clock.install()
            page.goto((self.batch / 'report.html').as_uri())
            self.assertEqual(page.locator('#cost-actor-kind').input_value(), 'agent')
            page.clock.fast_forward(1000)
            self.assertIn('活动 0.0', page.locator('#cost-elapsed').inner_text())
            page.locator('#cost-start').click()
            page.clock.fast_forward(2000)
            page.locator('#cost-pause').click()
            page.clock.fast_forward(3000)
            page.locator('#cost-start').click()
            page.clock.fast_forward(1000)
            page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true, value:true});document.dispatchEvent(new Event('visibilitychange'))")
            page.clock.fast_forward(4000)
            self.assertIn('已暂停', page.locator('#cost-status').inner_text())
            page.locator('#cost-finish').click()
            with page.expect_download() as download:
                page.locator('#cost-download').click()
            target = self.root / 'cost.json'
            download.value.save_as(target)
            cost = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(cost['batch_id'], state['batch_id'])
            self.assertEqual(cost['package_sha256'], state['package_sha256'])
            self.assertEqual(cost['base_revision'], state['revision'])
            self.assertEqual(cost['actor_kind'], 'agent')
            self.assertGreaterEqual(cost['active_elapsed_ms'], 3000)
            self.assertLess(cost['active_elapsed_ms'], 4000)
            self.assertGreaterEqual(cost['paused_elapsed_ms'], 7000)
            self.assertEqual(cost['attempt_counts']['patch_download_button_attempts'], 0)
            for forbidden in ['source_id', 'actor', 'state', 'quote', 'scores', 'workspace']:
                self.assertNotIn(forbidden, cost)
            self.assertEqual(self.read()['decisions'], [])
            self.assertEqual(errors, [])
            evidence = Path(os.environ.get('T3_EVIDENCE_DIR', 'work/t3-evidence'))
            evidence.mkdir(parents=True, exist_ok=True)
            for width in [420, 1400]:
                page.set_viewport_size(dict(width=width, height=900))
                page.locator('#review-cost').scroll_into_view_if_needed()
                page.screenshot(path=str(evidence / f'batch-cost-{width}.png'))
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            browser.close()

    def test_new_human_opinion_requires_explicit_reselection_and_keeps_history(self):
        initial = self.build()
        self.apply(self.patch(initial))
        source = self.sources[0]
        self.cli('export-template', '--candidate', initial['sources'][0]['candidates'][0]['value']['candidate_id'],
                 '--output', str(source / 'create.json'), workspace=source)
        path = source / 'create.json'
        patch = json.loads(path.read_text(encoding='utf-8'))
        patch.update(actor='agent-synthetic', reason='补录同一普通分区遗漏', edits=[])
        patch['creates'] = [dict(candidate_id='human-added', section_id='comments', fields=dict(
            status='needs_review', object='补录资料观点', evidence=initial['sources'][0]['candidates'][0]['value']['evidence']))]
        path.write_text(json.dumps(patch), encoding='utf-8')
        self.cli('apply', path, workspace=source)
        self.assertIn('E_BATCH_RESELECT_REQUIRED', self.cli('batch-refresh', ok=False).stderr)
        controller = Controller()
        controller.open_batch(self.batch)
        options = controller.batch_refresh_options()
        self.assertIn('human-added', [c['candidate_id'] for c in options['sources'][0]['choices']])
        self.assertNotIn('PRIVATE-SYNTHETIC', json.dumps(options))
        selection = {k: options[k] for k in ('batch_id', 'base_revision', 'package_sha256')}
        selection['sources'] = [dict(source_id=s['source_id'], revision=s['revision'], candidate_ids=(
            ['human-added'] if index == 0 else s['previous_ids'])) for index, s in enumerate(options['sources'])]
        controller.refresh_batch(selection)
        refreshed = self.read()
        self.assertEqual(refreshed['sources'][0]['view']['kind'], 'selected')
        self.assertEqual([c['value']['candidate_id'] for c in refreshed['sources'][0]['candidates']], ['human-added'])
        self.assertEqual(refreshed['issues'], [])
        self.assertEqual(refreshed['refresh_pending_issue_ids'], ['issue-1'])
        self.assertEqual(len(refreshed['decisions']), 2)
        self.assertIn('只读历史', (self.batch / 'report.html').read_text(encoding='utf-8'))

    @unittest.skipUnless(fixture.CHROME.is_file() and importlib.util.find_spec('playwright'), 'Chrome and Playwright needed')
    def test_browser_decision_then_original_form_correction_refresh_and_reopen(self):
        from playwright.sync_api import sync_playwright
        initial = self.build()
        controller = Controller()
        controller.open_batch(self.batch)
        sid = initial['sources'][0]['source']['source_id']
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(fixture.CHROME), headless=True)
            page = browser.new_page(offline=True, accept_downloads=True)
            errors, external = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: external.append(r.url) if not r.url.startswith('file:') else None)
            page.goto((self.batch / 'report.html').as_uri())
            page.locator('#actor').fill('agent-desktop-rehearsal')
            page.locator('#reason').fill('合成审核决定')
            page.locator('#decision-reason').fill('记录本来源个案处理')
            page.locator('#queue').click()
            with page.expect_download() as download:
                page.locator('#download').click()
            decisions = self.root / 'browser-decisions.json'
            download.value.save_as(decisions)
            self.assertIn('尚未应用', page.locator('#save-status').inner_text())
            self.assertEqual(self.read()['decisions'], [])
            controller.apply_batch(decisions)
            controller.recover_batch()
            page.reload()
            self.assertEqual(page.locator('.saved-decision').count(), 1)
            controller.open_batch_source(sid)
            page.get_by_role('link', name='在原工作区纠正观点').first.click()
            page.locator('#candidate').select_option(initial['sources'][0]['candidates'][0]['value']['candidate_id'])
            page.locator('#object').fill('普通表单修正后的资料范围')
            page.locator('#actor').fill('agent-desktop-rehearsal')
            page.locator('#reason').fill('合成原来源纠正')
            with page.expect_download() as download:
                page.locator('#download').click()
            correction = self.root / 'browser-correction.json'
            download.value.save_as(correction)
            controller.apply_patch(correction)
            self.assertEqual(controller.recover_batch()['material_status'], 'needs_refresh')
            controller.refresh_batch()
            controller.recover_batch()
            page.goto((self.batch / 'report.html').as_uri())
            self.assertIn('普通表单修正后的资料范围', page.locator('body').inner_text())
            self.assertIn('needs_revalidation', page.locator('.saved-decision').inner_text())
            self.assertEqual(page.locator('#issue option').count(), 0)
            self.assertEqual(errors, [])
            self.assertEqual(external, [])
            browser.close()
