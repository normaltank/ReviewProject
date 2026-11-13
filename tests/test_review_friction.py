"""Synthetic ranking, uncovered spans and browser identity-navigation regressions."""
from contextlib import closing
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from lxml import html
import test_batch_flow as fixture
from reviewproto.batch import BatchWorkspace
from reviewproto.batch_retrieval import entries, ranked_hits, retrieve, RANKING
from reviewproto.batch_render import render as render_batch
from reviewproto.core import ReviewError
from reviewproto.framework import framework_digest
from reviewproto.review_links import editor_link, unreferenced_ranges
from reviewproto.store import Workspace, encoded

CHROME = Path(os.environ.get('REVIEW_BROWSER_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))


class ReviewFrictionTests(unittest.TestCase):
    setUp = fixture.BatchFlowTests.setUp
    cli = fixture.BatchFlowTests.cli
    read = fixture.BatchFlowTests.read
    build = fixture.BatchFlowTests.build

    def custom_batch(self):
        path = self.root / 'friction-source.json'
        text = '😀重复句。\n重复句。未引用要求。\nUNSELECTED-SENTINEL'
        path.write_bytes(encoded(dict(schema_version=1, scores=[], sections=[
            dict(section_id='comments', label='评审意见', text=text, visibility='visibility_unknown'),
            dict(section_id='private', label='作者不可见', text='PRIVATE-ONLY-SENTINEL', visibility='internal_only')])))
        with closing(Workspace(self.root / 'friction-source')) as ws:
            state = ws.run(path, 'synthetic', 'json')
            first, second = state['candidates'][:2]
            patch = ws.review_template()
            patch.update(actor='synthetic-agent', reason='Synthetic navigation fixture', edits=patch['edits'][:2])
            repeated = dict(source_id=state['source']['source_id'], section_id='comments', start=6, end=10, quote='重复句。', precision='exact')
            patch['edits'][0]['fields']['evidence'].append(repeated)
            patch['edits'][1]['fields']['evidence'] = [repeated]
            state = ws.apply(patch)
        self.manifest['sources'][0].update(workspace=str(self.root / 'friction-source'), source_id=state['source']['source_id'],
            revision=state['revision'], candidate_ids=[first['candidate_id'], second['candidate_id']])
        self.manifest['issues'] = []
        self.build()
        return state

    def search(self, run_id='candidate-ranking', top_k=2):
        query = self.root / 'query.txt'
        query.write_text('查找合成观点', encoding='utf-8')
        with closing(BatchWorkspace(self.batch)) as ws:
            return retrieve(ws, query_path=query, run_id=run_id, method='lexical', top_k=top_k,
                score_provider=lambda query, quotes: [0.99, 1.0, 0.5, 0.2])

    def test_candidate_ranking_preserves_max_span_and_exact_cross_source_identity(self):
        corpus = [dict(source_id='a', candidate_id='same', evidence_index=0),
                  dict(source_id='a', candidate_id='same', evidence_index=1),
                  dict(source_id='b', candidate_id='same', evidence_index=0),
                  dict(source_id='a', candidate_id='other', evidence_index=0)]
        ranked = ranked_hits(corpus, [0.1, 0.8, 0.8, 0.8], 3)
        self.assertEqual([(h['source_id'], h['candidate_id'], h['evidence_index']) for h in ranked],
            [('a', 'same', 1), ('b', 'same', 0), ('a', 'other', 0)])
        self.assertEqual([h['evidence_index'] for h in ranked_hits(corpus[:2], [0.8, 0.8], 1)], [0])

    def test_product_ranking_and_legacy_sidecar_keep_distinct_meanings(self):
        self.custom_batch()
        run = self.search()
        self.assertEqual({k: run['config'][k] for k in RANKING}, RANKING)
        self.assertEqual([h['evidence_index'] for h in run['hits']], [1, 0])
        self.assertEqual(len({(h['source_id'], h['candidate_id']) for h in run['hits']}), 2)
        with closing(BatchWorkspace(self.batch)) as ws:
            state = ws.state()
            legacy = copy.deepcopy(run)
            legacy['run_id'] = 'historical-evidence'
            for key in RANKING:
                legacy['config'].pop(key)
            corpus = entries(state)
            legacy['hits'] = [dict(corpus[i], rank=i + 1, score=0.9) for i in range(2)]
            legacy['request_sha256'] = framework_digest({k: legacy[k] for k in ('query', 'config', 'input_sha256', 'top_k')})
            legacy.pop('validity');legacy.pop('sha256')
            legacy['sha256'] = framework_digest(legacy)
            path = self.batch / 'retrieval-runs/historical-evidence.json'
            path.write_bytes(encoded(legacy))
            original = path.read_bytes()
            restored = ws.recover()['retrieval_runs']
            old = next(r for r in restored if r['run_id'] == 'historical-evidence')
            self.assertEqual(old['hits'], legacy['hits'])
            self.assertEqual(path.read_bytes(), original)
            saved = ws.db.execute('SELECT payload FROM state').fetchone()[0]
            self.assertNotIn('retrieval_runs', json.loads(saved))
        with self.assertRaisesRegex(ReviewError, 'E_RETRIEVAL_RUN_CONFLICT'):
            self.search('historical-evidence')
        self.assertEqual(path.read_bytes(), original)
        tree = html.fromstring((self.batch / 'report.html').read_text(encoding='utf-8'))
        self.assertIn('命中 2 条，不同观点 2 个', tree.get_element_by_id('retrieval-results').text_content())
        self.assertIn('命中 2 条，不同观点 1 个', tree.find_class('historical-retrieval')[0].text_content())
        for link in tree.xpath('//a[starts-with(@href,"#evidence-")]'):
            self.assertIsNotNone(tree.get_element_by_id(link.get('href')[1:]))

    def test_complement_merges_intersections_and_preserves_unicode_positions(self):
        section = dict(section_id='comments', text='😀甲乙丙丁。\n后段。', visibility='visibility_unknown')
        def candidate(*spans):
            return dict(value=dict(section_id='comments', evidence=[dict(start=a, end=b, quote=section['text'][a:b]) for a, b in spans]))
        source = dict(candidates=[candidate((1, 4), (2, 5)), candidate((4, 6), (7, 8))])
        gaps = unreferenced_ranges(source, section)
        self.assertEqual(gaps, [dict(start=0, end=1, quote='😀'), dict(start=8, end=10, quote='段。')])
        self.assertEqual(unreferenced_ranges(source, dict(section, visibility='internal_only')), [])
        self.assertEqual(unreferenced_ranges(dict(candidates=[]), section), [dict(start=0, end=10, quote=section['text'])])

    def test_links_and_unreferenced_projection_are_readonly_and_public_selected_only(self):
        state = self.custom_batch()
        with closing(BatchWorkspace(self.batch)) as ws:
            frozen = ws.state()
            payload = ws.db.execute('SELECT payload FROM state').fetchone()[0]
            rendered = render_batch(frozen)
            self.assertEqual(ws.db.execute('SELECT payload FROM state').fetchone()[0], payload)
        tree = html.fromstring(rendered)
        self.assertNotIn('PRIVATE-ONLY-SENTINEL', rendered)
        gaps = tree.xpath('//a[@class="direct-add" and not(ancestor::details[@class="unreferenced-noise"])]')
        self.assertEqual(len(gaps), 1)
        noise = tree.find_class('unreferenced-noise')
        self.assertEqual(len(noise), 1)
        noise_parameters = parse_qs(urlsplit(noise[0].xpath('.//a[@class="direct-add"]')[0].get('href')).fragment.split('?', 1)[1])
        self.assertEqual((noise_parameters['start'], noise_parameters['end']), (['5'], ['6']))
        self.assertIn('不把折叠视为覆盖完成', rendered)
        parameters = parse_qs(urlsplit(gaps[0].get('href')).fragment.split('?', 1)[1])
        self.assertEqual(parameters['start'], ['10'])
        self.assertEqual(parameters['end'], [str(len(state['sections'][0]['text']))])
        self.assertEqual(set(parameters), {'source_id', 'base_revision', 'section_id', 'start', 'end'})
        for link in tree.xpath('//a[@class="direct-correction"]'):
            params = parse_qs(urlsplit(link.get('href')).fragment.split('?', 1)[1])
            self.assertEqual(set(params), {'source_id', 'base_revision', 'candidate_id'})
            self.assertNotIn('UNSELECTED-SENTINEL', link.get('href'))

    @unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
    def test_browser_candidate_route_selects_only_target_and_preserves_drafts_on_hashchange(self):
        from playwright.sync_api import sync_playwright
        state = self.custom_batch()
        with closing(BatchWorkspace(self.batch)) as ws:
            source = ws.state()['sources'][0]
        first, target = [c['candidate_id'] for c in state['candidates'][:2]]
        self.search()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
            page = browser.new_page(offline=True, accept_downloads=True, viewport=dict(width=420, height=900))
            errors, requests = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: requests.append(r.url))
            page.goto((self.batch / 'report.html').as_uri())
            link = page.locator('#retrieval-results a.direct-correction').nth(1)
            self.assertEqual(link.get_attribute('href'), editor_link(source, candidate_id=target))
            link.click()
            page.wait_for_selector('meta[name="review-editor-routing"]', state='attached')
            self.assertEqual(page.locator('meta[name="review-editor-routing"]').get_attribute('content'), 'identity-v1')
            draft = json.loads(page.locator('#patch').input_value())
            self.assertEqual([e['candidate_id'] for e in draft['edits']], [target])
            self.assertEqual(page.locator('#candidate').input_value(), target)
            page.locator('#object').fill('合成修改保留')
            before = page.locator('#patch').input_value()
            page.evaluate('(hash)=>location.hash=hash', urlsplit(editor_link(source, candidate_id=first)).fragment)
            page.wait_for_function("document.getElementById('message').textContent.includes('未切换定位')")
            self.assertEqual(page.locator('#patch').input_value(), before)
            page.locator('#patch').evaluate("e=>e.closest('details').open=true")
            page.locator('#patch').fill(before + ' ')
            advanced = page.locator('#patch').input_value()
            page.evaluate('(hash)=>location.hash=hash', urlsplit(editor_link(source, section_id='comments', start=6, end=10)).fragment)
            page.wait_for_timeout(80)
            self.assertEqual(page.locator('#patch').input_value(), advanced)
            self.assertEqual(page.locator('#candidate').input_value(), target)
            self.assertFalse(errors)
            self.assertFalse([u for u in requests if u.startswith(('http:', 'https:'))])
            browser.close()

    @unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
    def test_browser_unicode_range_routes_capture_without_creation_then_apply(self):
        from playwright.sync_api import sync_playwright
        state = self.custom_batch()
        with closing(BatchWorkspace(self.batch)) as ws:
            source = ws.state()['sources'][0]
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
            for start, end in ((0, 1), (6, 10), (4, 7)):
                with self.subTest(start=start, end=end):
                    page = browser.new_page(offline=True, viewport=dict(width=420, height=900))
                    page.goto(editor_link(source, section_id='comments', start=start, end=end))
                    draft = json.loads(page.locator('#patch').input_value())
                    self.assertEqual((draft['edits'], draft['creates']), ([], []))
                    self.assertEqual(page.locator('#route-source-range').inner_text(), state['sections'][0]['text'][start:end])
                    self.assertEqual(page.locator('#candidate').input_value(), '')
                    page.locator('#selection-create').click()
                    created = json.loads(page.locator('#patch').input_value())['creates'][0]
                    self.assertEqual(created['fields']['status'], 'needs_review')
                    self.assertEqual(created['fields']['action'], 'unknown')
                    evidence = created['fields']['evidence'][0]
                    self.assertEqual((evidence['start'], evidence['end'], evidence['quote']), (start, end, state['sections'][0]['text'][start:end]))
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 420)
                    if (start, end) == (4, 7):
                        payload = json.loads(page.locator('#patch').input_value())
                        payload.update(actor='synthetic-agent', reason='Explicit route creation')
                        with closing(Workspace(source['workspace'])) as ws:
                            saved = ws.apply(payload)
                            reopened = ws.recover()
                        view = next(d['value'] for d in reopened['decisions'] if d['candidate_id'] == created['candidate_id'])
                        self.assertEqual(view['status'], 'needs_review')
                        self.assertEqual(view['evidence'][0], evidence)
                        self.assertEqual(saved['source'], state['source'])
                    page.close()
            browser.close()

    @unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
    def test_browser_invalid_routes_do_not_fall_back_to_first_candidate(self):
        from playwright.sync_api import sync_playwright
        state = self.custom_batch()
        with closing(BatchWorkspace(self.batch)) as ws:
            source = ws.state()['sources'][0]
        valid = dict(source_id=state['source']['source_id'], base_revision=state['revision'], candidate_id=state['candidates'][1]['candidate_id'])
        ranged = dict(source_id=valid['source_id'], base_revision=valid['base_revision'], section_id='comments', start=6, end=10)
        bad = [urlencode(dict(valid, source_id='wrong')), urlencode(dict(valid, base_revision=0)),
            urlencode(dict(valid, candidate_id='missing')), urlencode(valid) + '&candidate_id=duplicate',
            urlencode(dict(valid, section_id='comments', start=0, end=1)), urlencode(dict(valid, unknown='x')),
            urlencode(dict(ranged, start=-1)), urlencode(dict(ranged, end=100000)), urlencode(dict(ranged, end=6)),
            urlencode(dict(ranged, section_id='missing')), urlencode(dict(ranged, start='06')),
            urlencode(dict(ranged, start='9007199254740993')), urlencode(ranged) + '&start=1',
            urlencode(valid) + '&invalid=%ZZ']
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
            for query in bad:
                with self.subTest(query=query):
                    page = browser.new_page(offline=True)
                    page.goto((Path(source['workspace']) / 'report.html').as_uri() + '#editor?' + query)
                    self.assertIn('定位链接无效', page.locator('#message').inner_text())
                    draft = json.loads(page.locator('#patch').input_value())
                    self.assertEqual((draft['edits'], draft['creates']), ([], []))
                    self.assertEqual(page.locator('#candidate').input_value(), '')
                    self.assertEqual(page.locator('#route-source-range').count(), 0)
                    page.close()
            browser.close()
