"""Synthetic acceptance boundaries for course evidence, comparison and drafts."""
from contextlib import closing
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from reviewproto.core import ReviewError, digest
from reviewproto.framework import framework_digest, source_text
from reviewproto.store import Workspace, encoded, template


CHROME = Path(os.environ.get('REVIEW_BROWSER_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))


def synthetic_package(root):
    root.mkdir()
    (root / 'sources').mkdir()
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('ppt/slides/slide1.xml', '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:sp><a:p><a:r><a:t>合成 条件</a:t></a:r><a:br/><a:r><a:t>若资料不足😀。</a:t></a:r></a:p><a:p><a:r><a:t>保留例外。</a:t></a:r></a:p></p:sp></p:sld>')
    ppt = content.getvalue()
    transcript = encoded([dict(id='s-1', start=10.25, end=20.5, ppt_page=1, text='机器合成转写：建议说明局限。', listen_flags=['not_listened'])])
    (root / 'sources' / 'course.pptx').write_bytes(ppt)
    (root / 'sources' / 'transcript.json').write_bytes(transcript)
    book = dict(schema_version=1, framework_id='synthetic-course', version='draft-1', title='合成候选规则', coverage_notes=['合成测试，非真实课程。'],
                sources=[dict(source_id='ppt', kind='pptx_native', file='sources/course.pptx', sha256=digest(ppt), verification='native_text'),
                         dict(source_id='asr', kind='transcript_json', file='sources/transcript.json', sha256=digest(transcript), verification='machine_unchecked')],
                rules=[dict(rule_id='rule-1', dimension_id='D01', title='合成条件规则', requirement='根据可用资料说明局限。', rule_type='recommendation', strength='recommended', strength_provenance='inferred',
                            applicable_when=['资料有限时'], exceptions=['不预设必须新增资料'], unknowns=['正式适用范围未知'], checks=['核实条件'], derivation='editorial_operationalization',
                            evidence=[dict(source_id='ppt', locator=dict(page=1, paragraph=0), start=0, end=15, quote='合成 条件\n若资料不足😀。'),
                                      dict(source_id='asr', locator=dict(pointer='/0/text', segment_id='s-1', time_range=[10.25, 20.5], ppt_page=1), start=7, end=14, quote='建议说明局限。')])])
    # Explicit offsets here are independent authored fixture values, checked below.
    book['rules'][0]['evidence'][0]['end'] = len('合成 条件\n若资料不足😀。')
    book['rules'][0]['evidence'][1]['start'] = len('机器合成转写：')
    book['rules'][0]['evidence'][1]['end'] = len('机器合成转写：建议说明局限。')
    path = root / 'book.json'
    path.write_bytes(encoded(book))
    return path, book


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'b.json'
        source.write_bytes(encoded(dict(schema_version=1, scores=[dict(label='创新性与科学性（1-5分）', raw_value=' 4.00 ')], sections=[
            dict(section_id='comments', label='评审意见', text='资料不足，应说明局限。\n已有充分资料，无需补充。', visibility='visibility_unknown'),
            dict(section_id='private', label='其他意见（作者不可见）', text='合成私密反例。', visibility='internal_only')])))
        self.ws = Workspace(self.root / 'workspace')
        self.addCleanup(self.ws.close)
        self.initial = self.ws.run(source, 'synthetic', 'json')
        self.path, self.book = synthetic_package(self.root / 'package')

    def import_book(self, book=None):
        self.path.write_bytes(encoded(self.book if book is None else book))
        return self.ws.import_framework(self.path)

    def review(self):
        state = self.ws.state()
        ids = [c['candidate_id'] for c in state['candidates'] if c['section_id'] == 'comments']
        result = self.ws.framework_template(candidate_id=ids[0], rule_id='rule-1')
        result.update(actor='synthetic-editor', reason='synthetic-development-comparison')
        result['alignments'][0].update(relation='condition_difference', provenance='inferred', rationale='合成 B 意见需保留条件。')
        result['proposals'] = [dict(proposal_id='proposal-1', rule_id='rule-1', kind='source_interpretation', after=dict(requirement='先核实已有资料，再决定是否补充或说明局限。'),
                                    rationale='合成支持与反例用于讨论，不作专业判断。', support_candidate_ids=[ids[0]], counter_candidate_ids=[ids[1]],
                                    validation_plan='另取独立稿件与教师双盲试评；记录作者与编辑负担。', rollback_condition='若新增不必要必改或丢失合法例外则回退。', unknowns=['独立稿件/教师分母未知；正式基线未确认。'])]
        return result

    def cli(self, *args, success=True):
        process = subprocess.run([sys.executable, '-m', 'reviewproto', *map(str, args), '--workspace', str(self.ws.path)], capture_output=True, encoding='utf-8', errors='replace')
        self.assertEqual(process.returncode, 0 if success else 2, process.stdout + process.stderr)
        return process

    def assert_persisted_review_state(self, returned):
        stored = json.loads(self.ws.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        projected = json.loads((self.ws.path / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(returned, stored)
        self.assertEqual(returned, projected)
        self.assertEqual(returned, self.ws.state())
        for review in returned['framework_reviews']:
            for entry in review['alignments'] + review['proposals']:
                self.assertEqual(entry['validity'], 'needs_revalidation')
        html = (self.ws.path / 'report.html').read_text(encoding='utf-8')
        self.assertIn('<strong>needs_revalidation</strong>', html)
        self.assertNotIn('<strong>current</strong>', html)

    def test_exact_native_and_machine_sources_freeze_idempotently_and_versions_conflict(self):
        data = (self.path.parent / 'sources/course.pptx').read_bytes()
        self.assertEqual(source_text('pptx_native', data, dict(page=1, paragraph=0)), '合成 条件\n若资料不足😀。')
        state = self.import_book()
        self.assertEqual(state['frameworks'][0]['sha256'], framework_digest(self.book))
        self.assertEqual(self.import_book(), state)
        changed = copy.deepcopy(self.book)
        changed['title'] = 'different same version'
        with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_VERSION_CONFLICT'):
            self.import_book(changed)
        self.assertEqual(self.ws.state(), state)
        changed['version'] = 'draft-2'
        self.assertEqual(len(self.import_book(changed)['frameworks']), 2)

    def test_wrong_hash_quote_pointer_time_and_segment_reject_without_state_changes(self):
        changes = [lambda b: b['sources'][0].update(sha256='0' * 64),
                   lambda b: b['rules'][0]['evidence'][0].update(quote='changed quote'),
                   lambda b: b['rules'][0]['evidence'][1]['locator'].update(pointer='/01/text'),
                   lambda b: b['rules'][0]['evidence'][1]['locator'].update(pointer='/0/missing'),
                   lambda b: b['rules'][0]['evidence'][1]['locator'].update(time_range=[10.25, 21]),
                   lambda b: b['rules'][0]['evidence'][1]['locator'].update(segment_id='wrong-id'),
                   lambda b: b['rules'][0]['evidence'][1]['locator'].update(ppt_page=2),
                   lambda b: b['sources'][1].update(verification='human_verified')]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                book = copy.deepcopy(self.book)
                change(book)
                with self.assertRaises(ReviewError):
                    self.import_book(book)
                self.assertEqual(self.ws.state(), self.initial)
        self.assertEqual(self.ws.db.execute('SELECT COUNT(*) FROM framework_sources').fetchone()[0], 0)

    def test_package_paths_escape_absolute_and_symlinks_are_rejected(self):
        for path in ('../outside.pptx', 'sources/../course.pptx', 'C:/outside.pptx', 'sources\\course.pptx', '/sources/course.pptx'):
            book = copy.deepcopy(self.book)
            book['sources'][0]['file'] = path
            with self.subTest(path=path), self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_PATH'):
                self.import_book(book)
        original = self.path.parent / 'sources/course.pptx'
        elsewhere = self.root / 'outside.pptx'
        original.rename(elsewhere)
        try:
            original.symlink_to(elsewhere)
        except OSError:
            self.skipTest('host cannot create symlinks')
        with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_LINK'):
            self.import_book()
        original.unlink()

    def test_zip_expansion_is_bounded_before_parsing(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('ppt/slides/slide1.xml', b'0' * 2_000_000)
        data = stream.getvalue()
        book = copy.deepcopy(self.book)
        book['sources'][0]['sha256'] = digest(data)
        (self.path.parent / 'sources/course.pptx').write_bytes(data)
        with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_ZIP_LIMIT'):
            self.import_book(book)

    def test_recover_uses_database_source_bytes_and_never_overwrites_modified_sources(self):
        state = self.import_book()
        frozen = self.ws.path / 'frameworks' / framework_digest(self.book) / 'sources/course.pptx'
        original = frozen.read_bytes()
        frozen.unlink()
        frozen.parent.parent.joinpath('book.json').unlink()
        (self.ws.path / 'report.html').unlink()
        (self.ws.path / 'state.json').unlink()
        # The original package can be absent; recovery must use authoritative bytes.
        (self.path.parent / 'sources/course.pptx').unlink()
        with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_SOURCE_MISSING'):
            self.ws.state()
        self.assertEqual(self.ws.recover(), state)
        self.assertEqual(frozen.read_bytes(), original)
        frozen.write_bytes(b'changed')
        for operation in (self.ws.state, self.ws.recover):
            with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_SOURCE_HASH'):
                operation()
        self.assertEqual(frozen.read_bytes(), b'changed')

    def test_frozen_book_and_source_links_are_protected(self):
        self.import_book()
        package = self.ws.path / 'frameworks' / framework_digest(self.book)
        book_path = package / 'book.json'
        original = book_path.read_bytes()
        book_path.write_bytes(b'changed book')
        for action in (self.ws.state, self.ws.recover):
            with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_SOURCE_HASH'):
                action()
        self.assertEqual(book_path.read_bytes(), b'changed book')
        book_path.write_bytes(original)
        frozen = package / 'sources/course.pptx'
        elsewhere = self.root / 'replacement.pptx'
        frozen.rename(elsewhere)
        try:
            frozen.symlink_to(elsewhere)
        except OSError:
            self.skipTest('host cannot create symlinks')
        for action in (self.ws.state, self.ws.recover):
            with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_LINK'):
                action()
        frozen.unlink()

    def test_review_draft_freezes_before_and_provenance_without_changing_scores_or_book(self):
        imported = self.import_book()
        payload = self.review()
        state = self.ws.apply_framework_review(payload)
        proposal = state['framework_reviews'][0]['proposals'][0]
        self.assertEqual(proposal['before'], self.book['rules'][0])
        self.assertEqual(proposal['after']['exceptions'], proposal['before']['exceptions'])
        self.assertEqual(proposal['status'], 'draft')
        self.assertEqual(proposal['review_status'], 'needs_professional_review')
        self.assertEqual(proposal['baseline_status'], 'baseline_confirmation_required')
        self.assertEqual(state['frameworks'], imported['frameworks'])
        self.assertEqual(state['scores'], self.initial['scores'])
        self.assertEqual(self.ws.apply_framework_review(payload), state)
        self.assertEqual(self.ws.recover(), state)
        html = (self.ws.path / 'report.html').read_text(encoding='utf-8')
        for label in ('冻结修改前', '建议修改后', '机器转写，未人工回听', 'PPT 第 1 页', '支持材料', '反例材料', '独立验证计划', '回退条件', '编辑操作化推断'):
            self.assertIn(label, html)

    def test_candidate_edit_append_and_withdraw_invalidate_history_without_erasing_snapshots(self):
        self.import_book()
        payload = self.review()
        reviewed = self.ws.apply_framework_review(payload)
        frozen = copy.deepcopy(reviewed['framework_reviews'][0]['alignments'][0]['candidate_snapshot'])
        patch = template(self.ws.state())
        patch.update(actor='editor', reason='manual change', edits=[dict(candidate_id=payload['alignments'][0]['candidate_id'], fields=dict(status='confirmed', action='new manual action'))])
        changed = self.ws.apply(patch)
        self.assert_persisted_review_state(changed)
        self.assertEqual(self.ws.apply(patch), changed)
        stale = changed['framework_reviews'][0]
        self.assertEqual(stale['alignments'][0]['validity'], 'needs_revalidation')
        self.assertEqual(stale['proposals'][0]['validity'], 'needs_revalidation')
        self.assertEqual(stale['alignments'][0]['candidate_snapshot'], frozen)
        self.assertIn('needs_revalidation', (self.ws.path / 'report.html').read_text(encoding='utf-8'))
        # A fresh comparison becomes stale when a separate B opinion is added.
        payload = self.review()
        payload['proposals'] = []
        self.ws.apply_framework_review(payload)
        patch = template(self.ws.state())
        patch.update(actor='editor', reason='missed view', edits=[], creates=[dict(candidate_id='added-opinion', section_id='comments', fields=dict(status='needs_review', evidence=[frozen['evidence'][0]]))])
        self.ws.apply(patch)
        self.assertEqual(self.ws.state()['framework_reviews'][-1]['alignments'][0]['validity'], 'needs_revalidation')
        payload = self.review()
        payload['proposals'] = []
        self.ws.apply_framework_review(payload)
        patch = template(self.ws.state())
        patch.update(actor='editor', reason='withdraw view', edits=[dict(candidate_id='added-opinion', fields=dict(status='withdrawn'))])
        self.ws.apply(patch)
        self.assertEqual(self.ws.state()['framework_reviews'][-1]['alignments'][0]['validity'], 'needs_revalidation')

    def test_model_append_returns_and_persists_stale_reviews_without_changing_frozen_evidence(self):
        self.import_book()
        reviewed = self.ws.apply_framework_review(self.review())
        frozen_review = copy.deepcopy(reviewed['framework_reviews'][0])
        section = next(s for s in reviewed['sections'] if s['section_id'] == 'comments')
        evidence = copy.deepcopy(frozen_review['alignments'][0]['candidate_snapshot']['evidence'])
        payload = dict(schema_version=1, source_id=reviewed['source']['source_id'], run_id='synthetic-framework-append',
                       extractor='synthetic-fixed-provider', model='synthetic-no-network', config={},
                       sections=[dict(section_id='comments', text_sha256=digest(section['text'].encode()))],
                       candidates=[dict(section_id='comments', evidence=evidence)])
        appended = self.ws.import_extractions(payload)
        self.assertEqual(len(appended['candidates']), len(reviewed['candidates']) + 1)
        self.assert_persisted_review_state(appended)
        self.assertEqual(self.ws.import_extractions(payload), appended)
        for previous, current in zip(frozen_review['alignments'] + frozen_review['proposals'],
                                     appended['framework_reviews'][0]['alignments'] + appended['framework_reviews'][0]['proposals']):
            previous['validity'] = 'needs_revalidation'
            self.assertEqual(previous, current)
        self.assertEqual(appended['scores'], reviewed['scores'])

    def test_both_draft_kinds_separate_editorial_changes_from_baseline_source_paraphrase(self):
        book = copy.deepcopy(self.book)
        book['rules'][0]['derivation'] = 'source_paraphrase'
        self.import_book(book)
        for index, kind in enumerate(('source_interpretation', 'publisher_requirement_change')):
            payload = self.review()
            payload['proposals'][0].update(proposal_id='provenance-proposal-' + str(index), kind=kind)
            state = self.ws.apply_framework_review(payload)
            proposal = state['framework_reviews'][-1]['proposals'][0]
            self.assertEqual(proposal['before'], book['rules'][0])
            self.assertEqual(proposal['before']['derivation'], 'source_paraphrase')
            self.assertNotEqual(proposal['after']['requirement'], proposal['before']['requirement'])
            self.assertEqual(proposal['after']['derivation'], 'editorial_operationalization')
            self.assertEqual(proposal['after_provenance'], 'editorial_proposal')
            self.assertEqual(proposal['evidence_scope'], 'baseline_only')
            self.assertEqual(proposal['status'], 'draft')
            self.assertEqual(proposal['after']['evidence'], proposal['before']['evidence'])
        html = (self.ws.path / 'report.html').read_text(encoding='utf-8')
        self.assertIn('草案增补未获原文确认', html)
        self.assertIn('原引文仅为修改前基线依据', html)
        self.assertIn('after_provenance=editorial_proposal', html)
        # Inputs cannot upgrade the edited draft to source-confirmed language.
        for forged in (dict(derivation='source_paraphrase'), dict(after_provenance='explicit_source')):
            payload = self.review()
            payload['proposals'][0]['proposal_id'] = 'forged-provenance'
            payload['proposals'][0]['after'].update(forged)
            with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_PROPOSAL_AFTER'):
                self.ws.apply_framework_review(payload)

    def test_support_counterexamples_cannot_bridge_permission_zones_or_inactive_ids(self):
        self.import_book()
        payload = self.review()
        private_id = next(c['candidate_id'] for c in self.ws.state()['candidates'] if c['section_id'] == 'private')
        for invalid in (private_id, 'unknown-from-other-workspace'):
            invalid_payload = copy.deepcopy(payload)
            invalid_payload['proposals'][0]['counter_candidate_ids'] = [invalid]
            with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_PROPOSAL_SCOPE'):
                self.ws.apply_framework_review(invalid_payload)
        cid = payload['proposals'][0]['counter_candidate_ids'][0]
        patch = template(self.ws.state())
        patch.update(actor='editor', reason='reject candidate', edits=[dict(candidate_id=cid, fields=dict(status='rejected'))])
        self.ws.apply(patch)
        payload['base_revision'] = self.ws.state()['revision']
        with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_PROPOSAL_SCOPE'):
            self.ws.apply_framework_review(payload)
        self.assertNotIn('framework_reviews', self.ws.state())

    def test_publication_authority_noop_and_forged_before_are_rejected(self):
        for key, value in [('status', 'published'), ('authority', 'approved'), ('formal_version', 'confirmed')]:
            book = copy.deepcopy(self.book)
            book[key] = value
            with self.assertRaises(ReviewError):
                self.import_book(book)
        self.import_book()
        for key, value in [('status', 'published'), ('authority', 'approved'), ('before', {'requirement': 'forged baseline'})]:
            payload = self.review()
            payload['proposals'][0][key] = value
            with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_PROPOSAL'):
                self.ws.apply_framework_review(payload)
        payload = self.review()
        payload['proposals'][0]['after'] = dict(requirement=self.book['rules'][0]['requirement'])
        with self.assertRaisesRegex(ReviewError, 'E_FRAMEWORK_PROPOSAL_NOOP'):
            self.ws.apply_framework_review(payload)
        self.assertEqual(self.ws.state()['revision'], self.initial['revision'] + 1)

    def test_cli_template_selects_target_and_records_replay_and_output_scope(self):
        self.cli('ingest-framework', self.path)
        cid = self.ws.state()['candidates'][0]['candidate_id']
        output = self.ws.path / 'framework-review.json'
        self.cli('framework-template', '--candidate', cid, '--rule', 'rule-1', '--output', output)
        payload = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(payload['alignments'][0]['candidate_id'], cid)
        self.assertEqual(payload['alignments'][0]['relation'], 'pending_comparison')
        self.cli('framework-template', '--output', output, success=False)
        self.cli('framework-template', '--output', self.ws.path / 'frameworks/danger.json', success=False)
        payload = self.review()
        output.write_bytes(encoded(payload))
        self.cli('apply-framework-review', output)
        self.cli('recover')
        runs = [json.loads(p.read_text(encoding='utf-8')) for p in (self.ws.path / 'runs').glob('*.json')]
        for command in ('ingest-framework', 'apply-framework-review'):
            run = next(r for r in runs if r['command'] == command)
            self.assertEqual(run['status'], 'complete')
            self.assertTrue((self.ws.path / run['replay']['input']).is_file())
            self.assertEqual(run['cost']['network_calls'], 0)
            if command == 'ingest-framework':
                before = self.ws.state()
                self.cli('ingest-framework', self.ws.path / run['replay']['input'])
                self.assertEqual(self.ws.state(), before)

    @unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
    def test_chrome_synthetic_import_comparison_draft_and_original_backlink(self):
        from playwright.sync_api import sync_playwright
        self.cli('ingest-framework', self.path)
        payload = self.review()
        payload_path = self.ws.path / 'synthetic-framework-review.json'
        payload_path.write_bytes(encoded(payload))
        self.cli('apply-framework-review', payload_path)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True, args=['--disable-background-networking'])
            try:
                context = browser.new_context(offline=True, viewport=dict(width=1200, height=900))
                page = context.new_page()
                requests, errors = [], []
                page.on('request', lambda request: requests.append(request.url))
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto((self.ws.path / 'report.html').as_uri())
                framework = page.locator('#frameworks')
                self.assertIn('正式效力', framework.inner_text())
                self.assertIn('冻结修改前', framework.inner_text())
                self.assertIn('建议修改后', framework.inner_text())
                self.assertIn('machine_unchecked', framework.inner_text())
                cid = payload['alignments'][0]['candidate_id']
                framework.get_by_role('link', name='B 观点 ' + cid, exact=True).click()
                self.assertTrue(page.url.endswith('#candidate-' + cid))
                self.assertIn('资料不足，应说明局限。', page.locator('#candidate-' + cid).inner_text())
                page.goto((self.ws.path / 'report.html').as_uri() + '#proposal-proposal-1')
                self.assertIn('baseline_confirmation_required', page.locator('#proposal-proposal-1').inner_text())
                self.assertFalse(errors)
                self.assertFalse([url for url in requests if url.startswith(('http:', 'https:'))])
                evidence_dir = os.environ.get('REVIEW_FRAMEWORK_EVIDENCE_DIR')
                if evidence_dir:
                    target = Path(evidence_dir)
                    target.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(target / 'synthetic-framework-draft.png'), full_page=True)
                    (target / 'browser-evidence.json').write_bytes(encoded(dict(browser=browser.version, external_requests=0, page_errors=errors,
                        source_origin='synthetic', chain=['ingest-framework', 'apply-framework-review', 'html-before-after', 'B-original-backlink'],
                        framework_sha256=framework_digest(self.book))))
            finally:
                browser.close()
