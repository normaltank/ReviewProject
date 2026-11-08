"""Browser acceptance uses only newly constructed synthetic evidence."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from reviewproto.store import Workspace

CHROME = Path(os.environ.get('REVIEW_BROWSER_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))


@unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
class EditorFlowTests(unittest.TestCase):
    def test_remove_existing_draft_limits_saved_decisions_and_empty_queue_can_add(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'synthetic.json'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': '第一条合成。\n第二条合成。', 'visibility': 'visibility_unknown'}]}), encoding='utf-8')
            with closing(Workspace(root / 'workspace')) as ws:
                initial = ws.run(source, 'synthetic', 'json')
                first, second = [c['candidate_id'] for c in initial['candidates']]
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
                    page = browser.new_page(offline=True, accept_downloads=True)
                    page.goto((ws.path / 'report.html').as_uri())
                    page.locator('#candidate').select_option(second)
                    page.locator('#object').fill('仅保存第二条')
                    page.locator('#draft-list').select_option(first)
                    page.locator('#delete-draft').click()
                    page.locator('#actor').fill('synthetic-editor')
                    page.locator('#reason').fill('仅修改指定目标')
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    saved = root / 'single.json'
                    download.value.save_as(saved)
                    payload = json.loads(saved.read_text(encoding='utf-8'))
                    self.assertEqual([e['candidate_id'] for e in payload['edits']], [second])
                    state = ws.apply(input_path=saved)
                    self.assertEqual([d['candidate_id'] for d in state['decisions']], [second])
                    page.locator('#delete-draft').click()
                    self.assertEqual(json.loads(page.locator('#patch').input_value())['edits'], [])
                    page.locator('#source-pane').evaluate('''e=>{const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);}''')
                    page.locator('#capture-selection').click()
                    page.locator('#selection-create').click()
                    self.assertEqual(len(json.loads(page.locator('#patch').input_value())['creates']), 1)
                    browser.close()

    def test_empty_candidate_queue_can_create_without_json(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'empty.json'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': '  ', 'visibility': 'visibility_unknown'}]}), encoding='utf-8')
            with closing(Workspace(root / 'workspace')) as ws:
                state = ws.run(source, 'synthetic', 'json')
                self.assertEqual(state['candidates'], [])
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
                    page = browser.new_page(offline=True)
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto((ws.path / 'report.html').as_uri())
                    page.locator('#source-pane').evaluate('''e=>{const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);}''')
                    page.locator('#capture-selection').click()
                    page.locator('#selection-create').click()
                    self.assertEqual(len(json.loads(page.locator('#patch').input_value())['creates']), 1)
                    self.assertFalse(errors)
                    browser.close()

    def test_dom_selection_drafts_relations_and_saved_reload(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'synthetic.json'
            text = '😀重复句。重复句。建议补数据。因为样本少。'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': text, 'visibility': 'visibility_unknown'},
                {'section_id': 'private', 'label': '作者不可见', 'text': '合成私密。', 'visibility': 'internal_only'}]}), encoding='utf-8')
            with closing(Workspace(root / 'workspace')) as ws:
                initial = ws.run(source, 'synthetic', 'json')
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
                    page = browser.new_page(offline=True, accept_downloads=True)
                    errors, requests = [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('request', lambda r: requests.append(r.url))
                    page.goto((ws.path / 'report.html').as_uri())
                    def select(a, b):
                        page.locator('#source-pane').evaluate('''(e, span)=>{const t=e.firstChild,r=document.createRange();r.setStart(t,span[0]);r.setEnd(t,span[1]);const s=getSelection();s.removeAllRanges();s.addRange(r);}''', [a, b])
                        page.locator('#capture-selection').click()
                    select(6, 10)  # UTF-16 offsets: second literal occurrence, after emoji.
                    page.locator('#selection-create').click()
                    page.locator('#object').fill('第二处')
                    create_id = page.locator('#draft-list').input_value()
                    patch = json.loads(page.locator('#patch').input_value())
                    self.assertEqual(patch['creates'][0]['fields']['evidence'][0]['start'], 5)
                    self.assertEqual(patch['creates'][0]['fields']['evidence'][0]['quote'], '重复句。')
                    select(16, 22)
                    page.locator('#selection-evidence').click()
                    page.locator('#add-reason').click()
                    page.locator('#reasons-rows input[data-key="text"]').fill('样本少')
                    page.locator('#reasons-rows input[type="checkbox"]').nth(1).check()
                    page.locator('#evidence-list button').nth(1).click()
                    self.assertIn('引用', page.locator('#message').inner_text())
                    page.locator('#add-condition').click()
                    page.locator('#conditions-rows input[data-key="text"]').fill('unknown')
                    page.locator('#add-alternative').click()
                    page.locator('#alternatives-rows select[data-key="relation"]').select_option('either_or')
                    page.locator('#actor').fill('synthetic-editor')
                    page.locator('#reason').fill('合成往返')
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    saved = root / 'draft.json'
                    download.value.save_as(saved)
                    exported = json.loads(saved.read_text(encoding='utf-8'))
                    self.assertEqual(exported['creates'][0]['candidate_id'], create_id)
                    self.assertEqual(exported['creates'][0]['fields']['alternatives'][0]['branches'][0]['condition'], 'unknown')
                    state = ws.apply(input_path=saved)
                    self.assertEqual(state['revision'], initial['revision'] + 1)
                    self.assertEqual(ws.apply(input_path=saved), state)
                    page.reload()
                    self.assertIn('第二处', page.locator('body').inner_text())
                    # Use a DOM caret to split the original full evidence, then
                    # edit both stable children independently and add/delete a draft.
                    page.locator('#source-pane').evaluate('''e=>{const r=document.createRange();r.setStart(e.firstChild,6);r.collapse(true);const s=getSelection();s.removeAllRanges();s.addRange(r);}''')
                    page.locator('#capture-selection').click()
                    page.locator('#selection-split').click()
                    self.assertFalse(page.locator('#patch').evaluate("e=>e.closest('details').open"))
                    children = json.loads(page.locator('#patch').input_value())['creates']
                    self.assertEqual(len(children), 2)
                    page.locator('#object').fill('左子观点')
                    page.locator('#status').select_option('confirmed')
                    page.locator('#draft-list').select_option(children[1]['candidate_id'])
                    page.locator('#object').fill('右子观点')
                    page.locator('#action').fill('单独动作')
                    page.locator('#draft-list').select_option(children[0]['candidate_id'])
                    self.assertEqual(page.locator('#object').input_value(), '左子观点')
                    self.assertEqual(page.locator('#status').input_value(), 'confirmed')
                    select(6, 10)
                    page.locator('#selection-create').click()
                    page.locator('#delete-draft').click()
                    self.assertEqual(len(json.loads(page.locator('#patch').input_value())['creates']), 2)
                    page.locator('#actor').fill('synthetic-editor')
                    page.locator('#reason').fill('合成拆分')
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    download.value.save_as(root / 'split.json')
                    split = json.loads((root / 'split.json').read_text(encoding='utf-8'))
                    self.assertEqual(split['edits'], [])
                    self.assertEqual([c['candidate_id'] for c in split['creates']], [c['candidate_id'] for c in children])
                    self.assertEqual(split['creates'][1]['fields']['action'], '单独动作')
                    self.assertEqual(ws.apply(input_path=root / 'split.json')['revision'], state['revision'] + 1)
                    self.assertFalse(errors)
                    self.assertFalse([u for u in requests if u.startswith(('http:', 'https:'))])
                    browser.close()

    def test_advanced_fields_survive_controls_and_reference_removal_remaps(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'synthetic.json'
            text = '合成重复。合成重复。'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': text, 'visibility': 'visibility_unknown'},
                {'section_id': 'private', 'label': '作者不可见', 'text': '私密。', 'visibility': 'internal_only'}]}), encoding='utf-8')
            with closing(Workspace(root / 'workspace')) as ws:
                ws.run(source, 'synthetic', 'json')
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
                    page = browser.new_page(offline=True)
                    page.goto((ws.path / 'report.html').as_uri())
                    patch = json.loads(page.locator('#patch').input_value())
                    fields = patch['edits'][0]['fields']
                    first = fields['evidence'][0]
                    fields['attributes'] = ['保留高级属性']
                    fields['evidence'] += [dict(first, start=0, end=5, quote=text[:5]), dict(first, start=5, end=10, quote=text[5:])]
                    fields['relations'] = [{'type': 'supports', 'target': patch['edits'][0]['candidate_id'], 'provenance': 'inferred', 'evidence_indices': [2]}]
                    fields['reasons'] = [{'text': '跨句理由', 'provenance': 'inferred', 'evidence_indices': [2]}]
                    page.get_by_text('高级：结构化字段与精确证据 JSON', exact=True).click()
                    page.locator('#patch').fill(json.dumps(patch, ensure_ascii=False))
                    page.locator('#object').fill('尚未载入不应覆盖')
                    self.assertEqual(json.loads(page.locator('#patch').input_value())['edits'][0]['fields']['attributes'], ['保留高级属性'])
                    page.locator('#import-advanced').click()
                    page.locator('#object').fill('普通表单修改')
                    page.locator('#evidence-list button').nth(1).click()
                    updated = json.loads(page.locator('#patch').input_value())['edits'][0]['fields']
                    self.assertEqual(updated['attributes'], ['保留高级属性'])
                    self.assertEqual(updated['reasons'][0]['evidence_indices'], [1])
                    self.assertEqual(updated['relations'][0]['evidence_indices'], [1])
                    self.assertEqual(updated['evidence'][1]['start'], 5)
                    page.locator('#add-section').select_option('private')
                    page.locator('#source-pane').evaluate('''e=>{const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);}''')
                    page.locator('#capture-selection').click()
                    page.locator('#selection-evidence').click()
                    self.assertIn('同分区', page.locator('#message').inner_text())
                    self.assertEqual(len(json.loads(page.locator('#patch').input_value())['edits'][0]['fields']['evidence']), 2)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertLessEqual(page.locator('#editor').evaluate('(e)=>e.scrollWidth'), page.locator('#editor').evaluate('(e)=>e.clientWidth'))
                    browser.close()

    def test_partial_and_malformed_advanced_import_preserve_current_fields_atomically(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'synthetic.json'
            source.write_text(json.dumps({'schema_version': 1, 'scores': [], 'sections': [
                {'section_id': 'comments', 'label': '评审意见', 'text': '合成意见。', 'visibility': 'visibility_unknown'}]}), encoding='utf-8')
            with closing(Workspace(root / 'workspace')) as ws:
                ws.run(source, 'synthetic', 'json')
                initial = ws.review_template()
                initial.update(actor='synthetic', reason='saved advanced fields')
                initial['edits'][0]['fields'].update(direction='negative', attributes=['keep'])
                ws.apply(initial)
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
                    page = browser.new_page(offline=True)
                    page.goto((ws.path / 'report.html').as_uri())
                    page.get_by_text('高级：结构化字段与精确证据 JSON', exact=True).click()
                    patch = json.loads(page.locator('#patch').input_value())
                    patch['edits'][0]['fields'] = {'evidence': patch['edits'][0]['fields']['evidence'], 'object': 'partial对象'}
                    page.locator('#patch').fill(json.dumps(patch, ensure_ascii=False))
                    page.locator('#import-advanced').click()
                    page.locator('#action').fill('普通动作')
                    valid = json.loads(page.locator('#patch').input_value())
                    self.assertEqual(valid['edits'][0]['fields']['direction'], 'negative')
                    self.assertEqual(valid['edits'][0]['fields']['attributes'], ['keep'])
                    bad = json.loads(json.dumps(valid))
                    bad['edits'][0]['fields']['object'] = 'malformed对象'
                    bad['edits'][0]['fields']['reasons'] = {}
                    page.locator('#patch').fill(json.dumps(bad, ensure_ascii=False))
                    page.locator('#import-advanced').click()
                    self.assertIn('未覆盖', page.locator('#message').inner_text())
                    self.assertEqual(page.locator('#object').input_value(), 'partial对象')
                    page.locator('#action').fill('拒绝坏JSON后继续修改')
                    kept = json.loads(page.locator('#patch').input_value())
                    self.assertEqual(kept['edits'][0]['fields']['object'], 'partial对象')
                    self.assertEqual(kept['edits'][0]['fields']['attributes'], ['keep'])
                    self.assertEqual(kept['edits'][0]['fields']['action'], '拒绝坏JSON后继续修改')
                    self.assertIsInstance(kept['edits'][0]['fields']['reasons'], list)
                    for invalid in [
                        {'alternatives': [{'relation': 'unknown', 'provenance': 'unknown', 'branches': {}}]},
                        {'reasons': [{'text': 'bad refs', 'provenance': 'unknown', 'evidence_indices': None}]},
                    ]:
                        bad = json.loads(json.dumps(kept))
                        bad['edits'][0]['fields'].update(invalid)
                        page.locator('#patch').fill(json.dumps(bad, ensure_ascii=False))
                        page.locator('#import-advanced').click()
                        self.assertEqual(json.loads(page.locator('#patch').input_value()), kept)
                        self.assertEqual(page.locator('#action').input_value(), '拒绝坏JSON后继续修改')
                    browser.close()
