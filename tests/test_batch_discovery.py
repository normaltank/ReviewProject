"""Synthetic acceptance through the CLI and browser; HTTP model is explicitly fake."""
import json
from contextlib import contextmanager
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import unittest
import threading

import test_batch_flow as fixture
from reviewproto.store import encoded
from reviewproto.core import digest


@contextmanager
def fake_model(result, finish_reason='stop', status=200, redirect=None):
    """Only this ephemeral loopback HTTP boundary is fake; no real model runs."""
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(status)
            if redirect:
                self.send_header('Location', redirect)
            self.end_headers()
            self.wfile.write(json.dumps(dict(choices=[dict(finish_reason=finish_reason,
                message=dict(content=json.dumps(result, ensure_ascii=False)))]), ensure_ascii=False).encode('utf-8'))
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def proposal():
    support = [dict(source_id='source-1', candidate_id='candidate-1', quote='资料不足，应说明局限。')]
    counter = [dict(source_id='source-2', candidate_id='candidate-1', quote='已有充分资料，无需补充。')]
    return dict(title='资料条件与补充负担的候选讨论', rule_id='rule-1', definition='资料覆盖条件候选概念',
        boundary='资料不足与充分两种判断分别保留，不推定普遍要求。', support=support, counter=counter,
        rationale='两份记录对资料范围的判断不同，需逐案核对。', unknowns=['尚未核验论文事实'],
        relation='condition_difference', possible_core_impact=False, alternatives=[dict(label='明确适用条件候选',
            requirement='资料不足时说明局限；资料充分时逐案核查是否仍需补充。', support=support, counter=counter,
            rationale='引用提供条件讨论线索，改写仍待专业审核。', benefits=['可明确条件'], costs=['增加核查负担'], unknowns=['作者负担未测'])])


class DiscoveryTests(unittest.TestCase):
    setUp = fixture.BatchFlowTests.setUp
    cli = fixture.BatchFlowTests.cli
    read = fixture.BatchFlowTests.read
    build = fixture.BatchFlowTests.build
    apply = fixture.BatchFlowTests.apply
    patch = fixture.BatchFlowTests.patch
    correct_source = fixture.BatchFlowTests.correct_source

    def test_baseline_discovers_from_empty_batch_and_decisions_survive_recovery(self):
        self.manifest['issues'] = []
        initial = self.build()
        self.cli('batch-discover', '--method', 'baseline', '--run-id', 'baseline-one', '--rule', 'rule-1')
        found = self.read()
        self.assertGreater(len(found['issues']), 0)
        self.assertEqual(found['analysis_runs'][0]['status'], 'complete')
        self.assertEqual(found['analysis_runs'][0]['method'], 'baseline')
        self.assertEqual(found['analysis_runs'][0]['model_requests'], 0)
        self.assertEqual(found['sources'], initial['sources'])
        self.assertEqual(found['issues'][0]['concept']['status'], 'candidate')
        self.assertEqual(found['issues'][0]['after_provenance'], 'editorial_proposal')
        self.assertEqual(found['issues'][0]['ranking']['distinct_source_records'], 1)
        self.assertEqual(found['issues'][0]['score_links'][0]['provenance'], 'unknown')
        patch = self.patch(found)
        for row in patch['decisions']:
            row['issue_id'] = found['issues'][0]['issue_id']
        self.apply(patch)
        self.cli('batch-discover', '--method', 'baseline', '--run-id', 'baseline-one', '--rule', 'rule-1')
        self.cli('batch-recover')
        self.assertEqual(len(self.read()['decisions']), 2)
        self.assertEqual(len(self.read()['analysis_runs']), 1)
        html = (self.batch / 'report.html').read_text(encoding='utf-8')
        self.assertIn('相关词/条件线索', html)
        self.assertIn('排序理由', html)
        self.assertNotIn('PRIVATE-SYNTHETIC', html)

    def test_fake_local_proposals_preserve_opposition_and_failure_then_invalidate_after_correction(self):
        self.manifest['issues'] = []
        self.build()
        good = proposal()
        bad = copy.deepcopy(good)
        bad['support'][0]['quote'] = '改写后的虚构原文'
        opposite = copy.deepcopy(good)
        opposite.update(title='同主题相反判断保留', support=good['counter'], counter=good['support'], alternatives=[])
        with fake_model(dict(issues=[good, bad, opposite])) as (endpoint, requests):
            result = self.cli('batch-discover', '--method', 'local', '--run-id', 'mock-local', '--rule', 'rule-1', '--endpoint', endpoint, ok=False)
        self.assertIn('status=partial', result.stdout)
        state = self.read()
        self.assertEqual(len(state['issues']), 2)
        self.assertEqual(state['issues'][0]['support'], state['issues'][1]['counter'])
        self.assertEqual(len(state['issues'][0]['alternatives']), 2)
        self.assertIsNone(state['issues'][0]['concept']['boundary_counterexample'])
        run = state['analysis_runs'][0]
        self.assertEqual(run['status'], 'partial')
        self.assertEqual(run['calls'][0]['errors'], ['E_MODEL_QUOTE'])
        self.assertEqual(run['model_requests'], 1)
        self.assertEqual(len(requests), 1)
        request = json.dumps(requests[0], ensure_ascii=False)
        self.assertNotIn(' 4.00 ', request)
        self.assertNotIn(self.manifest['sources'][0]['source_id'], request)
        self.assertNotIn('PRIVATE-SYNTHETIC', request)
        self.assertEqual(requests[0]['response_format']['json_schema']['schema']['additionalProperties'], False)
        self.assertTrue(run['calls'][0]['response_sha256'])
        self.assertEqual(state['issues'][0]['score_links'][0]['provenance'], 'unknown')
        self.correct_source()
        self.cli('batch-recover')
        self.assertEqual(self.read()['analysis_runs'][0]['validity'], 'needs_revalidation')
        self.assertEqual(self.read()['issues'][0]['validity'], 'needs_revalidation')
        for path in self.batch.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'PRIVATE-SYNTHETIC', path.read_bytes())

    def test_local_zero_truncation_bad_ids_context_and_redirect_remain_visible_without_fallback(self):
        self.manifest['issues'] = []
        self.build()
        bad = proposal()
        bad['support'][0]['candidate_id'] = 'private-or-foreign'
        scenarios = [
            ('mock-zero', dict(issues=[]), 'stop', 200, None, None, 'zero_candidates', None),
            ('mock-truncated', dict(issues=[proposal()]), 'length', 200, None, None, 'failed', 'E_MODEL_TRUNCATED'),
            ('mock-bad-id', dict(issues=[bad]), 'stop', 200, None, None, 'failed', 'E_MODEL_REFERENCE'),
            ('mock-context', dict(issues=[proposal()]), 'stop', 200, None, 500, 'failed', 'E_MODEL_CONTEXT_LIMIT'),
            ('mock-redirect', dict(issues=[proposal()]), 'stop', 302, 'http://127.0.0.1:1/no-follow', None, 'failed', 'E_LOCAL_PROPOSAL_REQUEST'),
            ('mock-request-error', dict(issues=[]), 'stop', 500, None, None, 'failed', 'E_LOCAL_PROPOSAL_REQUEST'),
        ]
        for run_id, result, finish, status, redirect, context, expected, error in scenarios:
            with self.subTest(run_id=run_id), fake_model(result, finish, status, redirect) as (endpoint, requests):
                args = ['batch-discover', '--method', 'local', '--run-id', run_id, '--rule', 'rule-1', '--endpoint', endpoint]
                if context:
                    args += ['--context-chars', str(context)]
                self.cli(*args, ok=expected == 'zero_candidates')
                state = self.read()
                run = state['analysis_runs'][-1]
                self.assertEqual(run['status'], expected)
                self.assertEqual(state['issues'], [])
                self.assertEqual(len(requests), 0 if context else 1)
                if error:
                    self.assertIn(error, run['errors'])
                if status in (302, 500):
                    self.assertEqual(run['calls'][0]['http_status'], status)
                    self.assertTrue(run['calls'][0]['response_sha256'])
                html = (self.batch / 'report.html').read_text(encoding='utf-8')
                self.assertIn(expected, html)
        before = self.read()
        self.assertIn('E_LOCAL_ENDPOINT_REQUIRED', self.cli('batch-discover', '--method', 'local', '--run-id', 'deny-cloud',
            '--endpoint', 'https://cloud.invalid/v1', ok=False).stderr)
        self.assertEqual(self.read(), before)

    @unittest.skipUnless(fixture.CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
    def test_browser_discovers_compares_sources_then_saves_two_decisions_and_reopens(self):
        from playwright.sync_api import sync_playwright
        self.manifest['issues'] = []
        self.build()
        rare = proposal()
        rare.update(title='低频核心问题候选', counter=[], alternatives=[], possible_core_impact=True)
        with fake_model(dict(issues=[proposal(), rare])) as (endpoint, _):
            self.cli('batch-discover', '--method', 'local', '--run-id', 'browser-mock', '--endpoint', endpoint)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(fixture.CHROME), headless=True)
            page = browser.new_page(offline=True, accept_downloads=True)
            errors, external = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: external.append(req.url) if not req.url.startswith('file:') else None)
            page.goto((self.batch / 'report.html').as_uri())
            issue = page.locator('.review-issue').first
            self.assertEqual(issue.locator('.alternative').count(), 2)
            self.assertIn('明确适用条件候选', issue.inner_text())
            self.assertIn('增加核查负担', issue.inner_text())
            self.assertIn('inferred', issue.inner_text())
            self.assertIn('unknown', issue.inner_text())
            self.assertIn('排序理由', issue.inner_text())
            self.assertIn('低频核心问题候选', page.locator('#rare-important').inner_text())
            issue.locator('.alternative').last.get_by_role('link').first.click()
            self.assertTrue(page.url.endswith(self.manifest['sources'][0]['candidate_ids'][0]))
            self.assertIn('资料不足，应说明局限。', page.locator('body').inner_text())
            page.locator('#actor').fill('synthetic-browser-reviewer')
            page.locator('#reason').fill('仅为mock页面往返，无真实专业审核')
            page.locator('#action').select_option('change')
            page.locator('#alternative').select_option('option-1')
            page.locator('#decision-reason').fill('候选条件改法待论文事实核验')
            page.locator('#queue').click()
            page.locator('#decision-type').select_option('framework_proposal_review')
            page.locator('#action').select_option('defer')
            page.locator('#decision-reason').fill('保留原规则；通用要求另议')
            page.locator('#queue').click()
            with page.expect_download() as download:
                page.locator('#download').click()
            patch = self.root / 'browser-discovered-decisions.json'
            download.value.save_as(patch)
            self.assertEqual(self.read()['decisions'], [])
            self.assertIn('尚未应用', page.locator('#save-status').inner_text())
            self.cli('batch-apply', patch)
            self.cli('batch-recover')
            page.reload()
            self.assertEqual(page.locator('.saved-decision').count(), 2)
            self.assertIn('候选条件改法待论文事实核验', page.locator('.saved-decision').first.inner_text())
            self.assertIn('option-1', page.locator('.saved-decision').first.inner_text())
            self.assertEqual(self.read()['decisions'][0]['alternative_id'], 'option-1')
            self.assertEqual(self.read()['decisions'][0]['selected_after']['requirement'], '资料不足时说明局限；资料充分时逐案核查是否仍需补充。')
            self.assertEqual(errors, [])
            self.assertEqual(external, [])
            browser.close()

    def test_pending_opinion_from_partial_run_remains_exploratory_and_explicit_score_link_is_preserved(self):
        ws = self.sources[0]
        initial = self.read(ws)
        candidate = initial['candidates'][0]
        payload = dict(schema_version=1, source_id=initial['source']['source_id'], run_id='mock-partial-opinions',
            extractor='explicitly-synthetic-no-model', model='mock', config={},
            sections=[dict(section_id='comments', text_sha256=digest(initial['sections'][0]['text'].encode('utf-8')))],
            candidates=[dict(section_id='comments', evidence=candidate['evidence'], relations=[dict(type='explains_score',
                target='工作量（1-5分）', provenance='explicit', evidence_indices=[0])]),
                dict(section_id='comments', evidence=[dict(start=0, end=2, quote='伪造')])])
        path = self.root / 'synthetic-partial.json'
        path.write_bytes(encoded(payload))
        self.cli('ingest-candidates', path, workspace=ws)
        current = self.read(ws)
        selected = next(c for c in current['candidates'] if c.get('run_id') == 'mock-partial-opinions')
        self.manifest['issues'] = []
        self.manifest['sources'][0].update(candidate_ids=[selected['candidate_id']], revision=current['revision'],
            view=dict(kind='run', run_id='mock-partial-opinions'))
        self.build()
        self.cli('batch-discover', '--method', 'baseline', '--run-id', 'from-partial')
        state = self.read()
        self.assertEqual(state['sources'][0]['candidates'][0]['value']['status'], 'pending_review')
        summary = state['source_run_status'][0]['runs'][0]
        self.assertEqual(summary['status'], 'partial')
        self.assertEqual(summary['errors_count'], 1)
        self.assertIn('partial', ' '.join(state['issues'][0]['unknowns']))
        self.assertEqual(state['issues'][0]['score_links'][0]['provenance'], 'explicit')
        self.assertEqual(state['issues'][0]['score_links'][0]['relations'][0]['target'], '工作量（1-5分）')

    def test_ambiguous_multi_alternative_change_rejected_atomically_and_selected_variant_is_frozen(self):
        self.manifest['issues'] = []
        self.build()
        with fake_model(dict(issues=[proposal()])) as (endpoint, _):
            self.cli('batch-discover', '--method', 'local', '--run-id', 'variant-mock', '--endpoint', endpoint)
        found = self.read()
        patch = self.patch(found)
        for row in patch['decisions']:
            row['issue_id'] = found['issues'][0]['issue_id']
        patch['decisions'][1]['action'] = 'change'
        self.assertIn('E_BATCH_ALTERNATIVE_REQUIRED', self.apply(patch, ok=False).stderr)
        self.cli('batch-recover')
        self.assertEqual(self.read(), found)
        patch['decisions'][1]['alternative_id'] = 'option-1'
        self.apply(patch)
        self.cli('batch-recover')
        saved = self.read()
        self.assertEqual(saved['decisions'][1]['alternative_id'], 'option-1')
        self.assertEqual(saved['decisions'][1]['selected_after'], found['issues'][0]['alternatives'][1]['after'])
        self.assertEqual(saved['decisions'][1]['alternative_sha256'], digest(encoded(found['issues'][0]['alternatives'][1])))
