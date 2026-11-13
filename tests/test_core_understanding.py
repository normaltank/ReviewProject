"""Behavioral regressions for independent opinions and appended machine runs."""
import concurrent.futures
import copy
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from reviewproto.core import ReviewError, SCORE_NAMES, digest, parse_docx
from reviewproto.store import Workspace, template
from reviewproto.understanding import effective_views
from test_core_pipeline import fixture


class UnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'synthetic.docx'
        self.source.write_bytes(fixture('样本规模不足。样本代表性不足。😀\n因为覆盖地区有限。若有资料可补案例；否则说明局限。'))
        self.ws = Workspace(self.root / 'workspace')
        self.addCleanup(self.ws.close)
        self.initial = self.ws.run(self.source, 'synthetic')

    def patch_value(self):
        value = template(self.ws.state())
        value.update(actor='synthetic-editor', reason='explicit behavioral regression', edits=[])
        return value

    def evidence(self, quote, sid='section-1'):
        section = next(s for s in self.initial['sections'] if s['section_id'] == sid)
        start = section['text'].index(quote)
        return dict(source_id=section['source_id'], section_id=sid, start=start, end=start + len(quote), quote=quote, precision='exact')

    def creation(self, cid, quote, **kwargs):
        return dict(candidate_id=cid, section_id='section-1', fields=dict(status='confirmed', evidence=[self.evidence(quote)]), **kwargs)

    def model_payload(self, run='run-one'):
        section = self.initial['sections'][0]
        return dict(schema_version=1, source_id=self.initial['source']['source_id'], run_id=run,
                    extractor='synthetic-fixed-provider', model='synthetic-no-network-model', config={'temperature': 0},
                    sections=[{'section_id': section['section_id'], 'text_sha256': digest(section['text'].encode())}],
                    candidates=[dict(section_id='section-1', external_id='opinion-0', evidence=[self.evidence('样本规模不足。')], negation='不足', review_flags=['synthetic_alignment_needs_review'])])

    def test_style_inheritance_hidden_numbering_cycles_and_vertical_merge_fail_closed(self):
        for kind in ('hidden', 'character_hidden', 'numbering', 'builtin_numbering', 'cycle', 'missing', 'default_hidden', 'table_hidden', 'vmerge'):
            with self.subTest(kind=kind):
                doc = Document(io.BytesIO(fixture()))
                if kind == 'vmerge':
                    doc.tables[0].cell(5, 3).merge(doc.tables[0].cell(6, 3))
                elif kind == 'default_hidden':
                    defaults = doc.styles.element.find(qn('w:docDefaults'))
                    defaults.append(OxmlElement('w:vanish'))
                elif kind == 'table_hidden':
                    style = doc.styles.add_style('SyntheticTable', WD_STYLE_TYPE.TABLE)
                    style.element.append(OxmlElement('w:webHidden'))
                    doc.tables[0].style = style
                elif kind == 'character_hidden':
                    parent = doc.styles.add_style('SyntheticCharParent', WD_STYLE_TYPE.CHARACTER)
                    child = doc.styles.add_style('SyntheticCharChild', WD_STYLE_TYPE.CHARACTER)
                    child.base_style = parent
                    parent.font.hidden = True
                    doc.tables[0].cell(5, 3).paragraphs[0].runs[0].style = child
                elif kind == 'builtin_numbering':
                    doc.tables[0].cell(5, 3).paragraphs[0].style = 'List Number'
                else:
                    parent = doc.styles.add_style('SyntheticParent', WD_STYLE_TYPE.PARAGRAPH)
                    child = doc.styles.add_style('SyntheticChild', WD_STYLE_TYPE.PARAGRAPH)
                    child.base_style = parent
                    doc.tables[0].cell(5, 3).paragraphs[0].style = child
                    if kind == 'hidden':
                        parent.font.hidden = True
                    elif kind == 'numbering':
                        parent.element.get_or_add_pPr().append(OxmlElement('w:numPr'))
                    elif kind == 'cycle':
                        parent.base_style = child
                    else:
                        parent.element.get_or_add_basedOn().set(qn('w:val'), 'SyntheticMissingAncestor')
                output = io.BytesIO()
                doc.save(output)
                with self.assertRaisesRegex(ReviewError, 'E_UNSUPPORTED_FEATURE|E_STYLE_CHAIN'):
                    parse_docx(output.getvalue())
        # Unused styles do not make an ordinary template unusable.
        doc = Document(io.BytesIO(fixture()))
        doc.styles.add_style('UnusedHidden', WD_STYLE_TYPE.CHARACTER).font.hidden = True
        output = io.BytesIO()
        doc.save(output)
        self.assertEqual(parse_docx(output.getvalue())['scores'], self.initial['scores'])

    def test_split_add_cross_sentence_relations_and_replacement_history(self):
        parent = self.initial['candidates'][0]['candidate_id']
        value = self.patch_value()
        first = self.creation('human-sample-size', '样本规模不足。', parent_ids=[parent], replaces=[parent])
        second = self.creation('human-representative', '样本代表性不足。', parent_ids=[parent], replaces=[parent])
        first['fields'].update(evidence=[self.evidence('样本规模不足。'), self.evidence('因为覆盖地区有限。')],
                               reasons=[dict(text='覆盖有限', provenance='explicit', evidence_indices=[1])],
                               relations=[dict(type='supports', target='human-representative', provenance='inferred', evidence_indices=[1])])
        value['creates'] = [first, second, self.creation('human-added-missed', '若有资料可补案例；否则说明局限。')]
        state = self.ws.apply(value)
        self.assertEqual(len(effective_views(state)), 3)
        self.assertEqual(state['scores'], self.initial['scores'])
        self.assertEqual(len([d for d in state['decisions'] if d['candidate_id'] == parent and d['value']['status'] == 'superseded']), 1)
        self.assertEqual(self.ws.apply(value), state)
        self.assertEqual(self.ws.run(self.source, 'synthetic'), state)
        self.ws.operation('recover', self.ws.state)
        saved = json.loads((self.ws.path / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(saved, state)
        self.assertTrue(all(d['actor'] and d['reason'] and d['at'] for d in state['decisions']))

    def test_score_comparison_uses_current_relations_without_changing_score(self):
        patch = self.patch_value()
        cid = 'human-score-association'
        creation = self.creation(cid, '样本规模不足。')
        creation['fields'].update(status='needs_review', relations=[dict(
            type='explains_score', target=self.initial['scores'][0]['label'],
            provenance='inferred', evidence_indices=[0])])
        patch['creates'] = [creation]
        state = self.ws.apply(patch)
        report = (self.ws.path / 'report.html').read_text(encoding='utf-8')
        score_table = report.split('<section id="score-comparison">', 1)[1].split('</section>', 1)[0]
        self.assertIn('#candidate-' + cid, score_table)
        self.assertIn('inferred', score_table)
        self.assertIn('needs_review', score_table)
        self.assertEqual(state['scores'], self.initial['scores'])
        patch = self.patch_value()
        patch['edits'] = [{'candidate_id': cid, 'fields': {'status': 'rejected'}}]
        self.ws.apply(patch)
        report = (self.ws.path / 'report.html').read_text(encoding='utf-8')
        score_table = report.split('<section id="score-comparison">', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('#candidate-' + cid, score_table)

    def test_rejection_withdrawal_and_legacy_patch_do_not_erase_history(self):
        cid = self.initial['candidates'][0]['candidate_id']
        value = self.patch_value()
        value['edits'] = [{'candidate_id': cid, 'fields': {'status': 'confirmed', 'object': 'independent opinion'}}]
        state = self.ws.apply(value)
        self.assertEqual(len(effective_views(state)), 1)
        for status in ('rejected', 'withdrawn'):
            value = self.patch_value()
            value['edits'] = [{'candidate_id': cid, 'fields': {'status': status}}]
            state = self.ws.apply(value)
            self.assertEqual(effective_views(state), [])
        self.assertEqual(len(state['decisions']), 3)
        self.assertEqual(state['candidates'], self.initial['candidates'])

    def test_model_versions_append_rejected_rows_and_zero_failure_are_explicit(self):
        first = self.model_payload()
        forged = copy.deepcopy(first['candidates'][0])
        forged['evidence'][0]['quote'] = 'forged synthetic quotation'
        first['candidates'].append(forged)
        state = self.ws.import_extractions(first)
        record = state['extraction_runs'][0]
        self.assertEqual(record['status'], 'partial')
        operation = next(json.loads(raw) for raw, in self.ws.db.execute("SELECT payload FROM runs") if json.loads(raw)['command'] == 'ingest-candidates')
        replay_file = self.ws.path / operation['replay']['input']
        self.assertEqual(json.loads(replay_file.read_text(encoding='utf-8')), first)
        self.assertEqual(record['rejected'][0]['error_code'], 'E_EVIDENCE_QUOTE')
        self.assertEqual(len(record['accepted_ids']), 1)
        accepted = next(c for c in state['candidates'] if c['candidate_id'] == record['accepted_ids'][0])
        self.assertIn('model_semantics_unverified', accepted['review_flags'])
        self.assertIn('synthetic_alignment_needs_review', accepted['review_flags'])
        self.assertEqual(self.ws.import_extractions(first), state)
        value = self.patch_value()
        value['edits'] = [{'candidate_id': record['accepted_ids'][0], 'fields': {'status': 'confirmed', 'object': 'human correction'}}]
        human = self.ws.apply(value)['decisions']
        second = self.model_payload('run-two')
        state = self.ws.import_extractions(second)
        self.assertEqual(state['decisions'], human)
        self.assertEqual(len(effective_views(state)), 1)
        self.assertEqual(len(state['candidates']), len(self.initial['candidates']) + 2)
        with self.assertRaisesRegex(ReviewError, 'E_EXTRACTION_RUN_CONFLICT'):
            self.ws.import_extractions(dict(second, model='different'))
        for run, status in [('empty', 'zero_candidates'), ('failed', 'failed')]:
            payload = dict(self.model_payload(run), candidates=[])
            if run == 'failed':
                payload.update(status='failed', errors=['E_PROVIDER_JSON'])
            state = self.ws.import_extractions(payload)
            self.assertEqual(state['extraction_runs'][-1]['status'], status)
        self.assertEqual(state['scores'], self.initial['scores'])

    def test_new_operations_protect_frozen_fields_and_cross_section_evidence(self):
        for mutation in ('scores', 'cross_section', 'machine_confirmed', 'unknown_concept'):
            value = self.patch_value()
            creation = self.creation('human-protected-test', '样本规模不足。')
            if mutation == 'scores':
                creation['fields']['scores'] = []
            elif mutation == 'cross_section':
                creation['fields']['evidence'] = [self.evidence('内部意见', 'section-2')]
            elif mutation == 'unknown_concept':
                creation['fields']['concept_ids'] = ['invented-without-registry']
            else:
                payload = self.model_payload('bad-status')
                payload['candidates'][0]['status'] = 'confirmed'
                state = self.ws.import_extractions(payload)
                self.assertEqual(state['extraction_runs'][-1]['rejected'][0]['error_code'], 'E_MACHINE_STATUS')
                self.assertEqual(effective_views(state), [])
                continue
            value['creates'] = [creation]
            before = self.ws.state()
            with self.assertRaises(ReviewError):
                self.ws.apply(value)
            self.assertEqual(self.ws.state(), before)

    def test_concept_registry_and_candidate_a_links_preserve_provenance(self):
        cid = self.initial['candidates'][0]['candidate_id']
        concept = dict(concept_id='concept-size', name='样本规模', definition='评价数量是否适合研究设计',
                       positive_examples=['样本规模不足'], negative_examples=['代表性不足'], boundary='不等同样本代表性',
                       status='pending_confirmation', sources=[{'source_id': self.initial['source']['source_id'], 'candidate_id': cid}])
        value = self.patch_value()
        value['concepts'] = [concept]
        value['edits'] = [{'candidate_id': cid, 'fields': {'status': 'confirmed', 'concept_ids': ['concept-size']}}]
        state = self.ws.apply(value)
        self.assertEqual(state['concepts'][0]['status'], 'pending_confirmation')
        duplicate = self.patch_value()
        duplicate['concepts'] = [dict(concept, concept_id='concept-duplicate')]
        with self.assertRaisesRegex(ReviewError, 'E_CONCEPT_DUPLICATE_NAME'):
            self.ws.apply(duplicate)
        revised = self.patch_value()
        revised['concepts'] = [dict(concept, definition='经编辑澄清的数量适配定义')]
        state = self.ws.apply(revised)
        self.assertEqual(len(state['concept_history']), 2)
        self.assertEqual(state['concept_history'][-1]['previous']['definition'], concept['definition'])
        clause = dict(clause_id='a-candidate-one', text='须说明研究局限', source_kind='direct_source_quote',
                      sources=[dict(source_id='synthetic-slide-source', sha256='a' * 64, page=14, locator={'paragraph': 2}, quote='须说明研究局限')])
        payload = {'schema_version': 1, 'clauses': [clause]}
        state = self.ws.import_clauses(payload)
        self.assertEqual(state['clauses'][0]['status'], 'candidate')
        self.assertEqual(self.ws.import_clauses(payload), state)
        bad = copy.deepcopy(payload)
        bad['clauses'][0]['status'] = 'formal'
        with self.assertRaisesRegex(ReviewError, 'E_CLAUSE_SHAPE'):
            self.ws.import_clauses(bad)
        value = self.patch_value()
        value['edits'] = [{'candidate_id': cid, 'fields': {'clause_links': [dict(clause_id='a-candidate-one', relation='pending_comparison', provenance='unknown', evidence_indices=[0])],
                                                        'relations': [dict(type='explains_score', target=SCORE_NAMES[0], provenance='inferred', evidence_indices=[0])]}}]
        state = self.ws.apply(value)
        self.assertEqual(state['decisions'][-1]['value']['clause_links'][0]['relation'], 'pending_comparison')
        self.assertEqual(state['scores'], self.initial['scores'])
        self.assertEqual(state['versions']['framework'], 'unavailable')

    def test_concurrent_machine_import_idempotency_and_projection_failure_recovery(self):
        payload = self.model_payload()
        def ingest():
            ws = Workspace(self.ws.path)
            try:
                return ws.import_extractions(payload)['revision']
            finally:
                ws.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(lambda _: ingest(), range(2))), [1, 1])
        self.assertEqual(len(self.ws.state()['extraction_runs']), 1)
        with patch('reviewproto.render.render', side_effect=OSError('synthetic interrupted projection')):
            with self.assertRaises(OSError):
                self.ws.import_extractions(self.model_payload('recovery-run'))
        self.assertEqual(len(self.ws.state()['extraction_runs']), 2)
        self.ws.operation('recover', self.ws.state)
        saved = json.loads((self.ws.path / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(saved, self.ws.state())

    def test_structured_json_and_real_csv_shape_freeze_source_scores_sections(self):
        rows = [['期刊名称', 'synthetic journal', '稿件ID', 'SYNTHETIC-ID', '投稿日期', 'synthetic date'],
                ['稿件标题', 'synthetic title', '', '', '', ''],
                [SCORE_NAMES[0], '4', SCORE_NAMES[1], '4', SCORE_NAMES[2], '4'],
                [SCORE_NAMES[3], '3', '', '', '', ''],
                ['评审意见', '样本规模不足。\n另一段😀', '', '', '', ''],
                ['其他意见（作者不可见）', '内部合成意见', '', '', '', '']]
        stream = io.StringIO(newline='')
        csv.writer(stream).writerows(rows)
        data = stream.getvalue().encode('utf-8-sig')
        structured = dict(schema_version=1, scores=[{'label': SCORE_NAMES[0], 'raw_value': ' 4.0 '}],
                          sections=[{'section_id': 'section-one', 'label': '评审意见', 'text': '结构化合成评论😀'}],
                          metadata={'reviewer_name': 'synthetic unverified label'})
        for kind, content in [('csv', data), ('json', json.dumps(structured, ensure_ascii=False).encode())]:
            path = self.root / ('structured.' + kind)
            path.write_bytes(content)
            ws = Workspace(self.root / (kind + '-workspace'))
            try:
                state = ws.run(path, 'synthetic', kind)
                self.assertEqual((ws.path / ('source.' + kind)).read_bytes(), content)
                self.assertEqual(state['source']['source_id'], digest(content))
                self.assertEqual(state['review']['reviewer_id'], 'unknown')
                self.assertFalse(state['source']['submitted_version_confirmed'])
                if kind == 'csv':
                    self.assertEqual(state['sections'][1]['visibility'], 'internal_only')
                    self.assertEqual([s['raw_value'] for s in state['scores']], ['4', '4', '4', '3'])
                self.assertEqual(ws.run(path, 'synthetic', kind), state)
                (ws.path / ('source.' + kind)).write_bytes(content + b' ')
                with self.assertRaisesRegex(ReviewError, 'E_SOURCE_CHANGED'):
                    ws.state()
            finally:
                ws.close()

    @unittest.skipUnless(os.getenv('REVIEW_BROWSER_BINARY'), 'local Chromium needed')
    def test_browser_split_and_add_download_apply_persist(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            try:
                page = browser.new_page(offline=True, accept_downloads=True)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto((self.ws.path / 'report.html').as_uri())
                page.locator('#actor').fill('synthetic-browser-editor')
                page.locator('#reason').fill('split independent opinions')
                page.locator('#split-offset').fill(str(len('样本规模不足。')))
                page.locator('#split').click()
                generated = json.loads(page.locator('#patch').input_value())
                self.assertEqual(len(generated['creates']), 2)
                for creation in generated['creates']:
                    creation['fields']['status'] = 'confirmed'
                page.locator('#patch').fill(json.dumps(generated, ensure_ascii=False))
                with page.expect_download() as download:
                    page.locator('#download').click()
                target = self.ws.path / 'browser-split.json'
                download.value.save_as(target)
                state = self.ws.apply(input_path=target)
                self.assertEqual(len(effective_views(state)), 2)
                page.reload()
                page.locator('#actor').fill('synthetic-browser-editor')
                page.locator('#reason').fill('add missed opinion')
                page.locator('#add-start').fill('0')
                page.locator('#add-end').fill(str(len('样本规模不足。')))
                page.locator('#add-opinion').click()
                with page.expect_download() as download:
                    page.locator('#download').click()
                target = self.ws.path / 'browser-add.json'
                download.value.save_as(target)
                state = self.ws.apply(input_path=target)
                self.assertEqual(len(state['candidates']), len(self.initial['candidates']) + 3)
                self.assertFalse(errors, errors)
                page.reload()
                self.assertIn('human_created', page.locator('body').inner_text())
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
