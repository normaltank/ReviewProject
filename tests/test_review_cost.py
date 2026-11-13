"""Synthetic offline-browser checks for the independent review-cost sidecar."""

import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from reviewproto.core import digest
from reviewproto.store import Workspace


CHROME = Path(os.environ.get('REVIEW_BROWSER_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))


@unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
class ReviewCostBrowserTests(unittest.TestCase):
    def test_explicit_timer_exports_separate_private_minimal_observation_and_patch_applies(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'synthetic.json'
            source.write_text(json.dumps({'schema_version': 1,
                'scores': [{'label': '创新性与科学性（1-5分）', 'raw_value': '4.375-SCORE-SENTINEL'}],
                'sections': [{'section_id': 'comments', 'label': '评审意见',
                              'text': '合成原文 SENTINEL-TEXT。建议解释方法。', 'visibility': 'visibility_unknown'}]}, ensure_ascii=False), encoding='utf-8')
            with closing(Workspace(root / 'workspace')) as ws:
                state = ws.run(source, 'synthetic', 'json')
                state = ws.import_extractions({'schema_version': 1, 'source_id': state['source']['source_id'],
                    'run_id': 'synthetic-cost-run', 'extractor': 'synthetic', 'model': 'fixed-no-model', 'config': {},
                    'sections': [{'section_id': 'comments', 'text_sha256': digest(state['sections'][0]['text'].encode())}],
                    'candidates': []})
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True, args=['--disable-background-networking'])
                    try:
                        context = browser.new_context(offline=True, accept_downloads=True, viewport={'width': 1100, 'height': 900})
                        page = context.new_page()
                        requests, errors = [], []
                        page.on('request', lambda request: requests.append(request.url))
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto((ws.path / 'report.html').as_uri())
                        self.assertEqual(page.locator('#cost-actor-kind').input_value(), 'unknown')
                        page.locator('#action').fill('before-start-does-not-count')
                        page.locator('#cost-start').click()
                        self.assertIn('请先填写', page.locator('#cost-status').inner_text())
                        page.locator('#actor').fill('synthetic-cost-agent')
                        page.locator('#reason').fill('synthetic split validation')
                        page.locator('#cost-actor-kind').select_option('agent')
                        page.locator('#cost-arm').select_option('run:synthetic-cost-run')
                        page.locator('#cost-start').click()
                        page.wait_for_timeout(180)
                        page.locator('#action').fill('synthetic input event')
                        page.locator('#split-offset').fill('5')
                        page.locator('#split').click()
                        with page.expect_download() as patch_download:
                            page.locator('#download').click()
                        patch_path = ws.path / 'synthetic-cost-patch.json'
                        patch_download.value.save_as(patch_path)
                        page.locator('#cost-pause').click()
                        active_at_pause = page.evaluate('costSession.active_elapsed_ms')
                        # The 250ms display tick may leave a 350ms wall wait
                        # observing only 100-200ms. Wait for an actual snapshot.
                        # evaluate polling preserves this page's strict CSP;
                        # wait_for_function uses an eval rejected by that policy.
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            if page.evaluate('costSession.paused_elapsed_ms') >= 350:
                                break
                            page.wait_for_timeout(25)
                        self.assertGreaterEqual(page.evaluate('costSession.paused_elapsed_ms'), 350)
                        self.assertAlmostEqual(page.evaluate('costSession.active_elapsed_ms'), active_at_pause, delta=1)
                        self.assertGreater(page.evaluate('costSession.paused_elapsed_ms'), 200)
                        page.locator('#cost-start').click()
                        page.wait_for_timeout(150)
                        # Exercise the browser visibility handler without opening a new visible app.
                        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
                        self.assertIn('已暂停', page.locator('#cost-status').inner_text())
                        hidden_active = page.evaluate('costSession.active_elapsed_ms')
                        page.wait_for_timeout(150)
                        self.assertEqual(page.evaluate('costSession.active_elapsed_ms'), hidden_active)
                        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false})")
                        page.locator('#cost-start').click()
                        page.locator('#cost-finish').click()
                        with page.expect_download() as observation_download:
                            page.locator('#cost-download').click()
                        observation_path = root / 'review-cost.json'
                        observation_download.value.save_as(observation_path)
                        observation = json.loads(observation_path.read_text(encoding='utf-8'))
                        self.assertEqual(set(observation), {'artifact_type','schema_version','session_id','source_id','base_revision','actor','actor_kind','arm','started_at_utc','finished_at_utc','active_elapsed_ms','paused_elapsed_ms','attempt_counts'})
                        self.assertEqual(observation['artifact_type'], 'review_cost_observation')
                        self.assertEqual(observation['schema_version'], 1)
                        self.assertEqual(observation['actor_kind'], 'agent')
                        self.assertEqual(observation['actor'], 'synthetic-cost-agent')
                        self.assertEqual(observation['arm'], {'kind': 'extraction_run', 'run_id': 'synthetic-cost-run'})
                        self.assertEqual(observation['source_id'], state['source']['source_id'])
                        self.assertEqual(observation['base_revision'], state['revision'])
                        self.assertGreater(observation['active_elapsed_ms'], 200)
                        self.assertGreater(observation['paused_elapsed_ms'], 400)
                        self.assertGreater(observation['finished_at_utc'], observation['started_at_utc'])
                        self.assertEqual(observation['attempt_counts'], {'editor_input_events': 2, 'split_button_attempts': 1, 'add_opinion_button_attempts': 0, 'patch_download_button_attempts': 1})
                        content = observation_path.read_text(encoding='utf-8')
                        for forbidden in ('SENTINEL-TEXT', 'SCORE-SENTINEL', 'quote', 'scores', 'api_key', 'synthetic input event'):
                            self.assertNotIn(forbidden, content)
                        patch = json.loads(patch_path.read_text(encoding='utf-8'))
                        self.assertNotIn('attempt_counts', patch)
                        applied = ws.apply(input_path=patch_path)
                        self.assertEqual(len(applied['candidates']), len(state['candidates']) + 2)
                        self.assertEqual(applied['scores'], state['scores'])
                        self.assertFalse([url for url in requests if url.startswith(('http:', 'https:'))])
                        self.assertFalse(errors)
                        evidence_dir = os.environ.get('REVIEW_COST_EVIDENCE_DIR')
                        if evidence_dir:
                            target = Path(evidence_dir)
                            target.mkdir(parents=True, exist_ok=True)
                            (target / 'observation-agent-synthetic.json').write_text(content, encoding='utf-8')
                            (target / 'browser-summary.json').write_text(json.dumps({'status': 'passed', 'network_requests': 0,
                                'page_errors': errors, 'patch_applied': True, 'real_human_observations': 0,
                                'visibility_test': 'synthetic visibilitychange dispatched in real Chrome'}, indent=2) + '\n', encoding='utf-8')
                            page.locator('#review-cost').screenshot(path=str(target / 'cost-desktop.png'))
                            page.set_viewport_size({'width': 390, 'height': 844})
                            page.locator('#review-cost').screenshot(path=str(target / 'cost-mobile.png'))
                            self.assertLessEqual(page.locator('#review-cost').evaluate('(e)=>e.scrollWidth'), page.locator('#review-cost').evaluate('(e)=>e.clientWidth'))
                    finally:
                        browser.close()


if __name__ == '__main__':
    unittest.main()
