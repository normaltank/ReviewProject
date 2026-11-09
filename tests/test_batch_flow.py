"""Synthetic public CLI and browser acceptance for trusted multi-source review."""
import copy
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from reviewproto.store import encoded
from reviewproto.core import digest
from test_framework_flow import synthetic_package

CHROME = Path(os.environ.get('REVIEW_BROWSER_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))


class BatchFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.batch = self.root / 'batch'
        self.sources = []
        for index, text in enumerate(('资料不足，应说明局限。', '已有充分资料，无需补充。')):
            source = self.root / f'input-{index}.json'
            source.write_bytes(encoded(dict(schema_version=1, scores=[dict(label='工作量（1-5分）', raw_value=' 4.00 ')], sections=[
                dict(section_id='comments', label='评审意见', text=text, visibility='visibility_unknown'),
                dict(section_id='private', label='其他意见（作者不可见）', text='PRIVATE-SYNTHETIC-DO-NOT-COPY', visibility='internal_only')])) )
            ws = self.root / f'source-{index}'
            self.cli('run', source, '--format', 'json', '--origin', 'synthetic', workspace=ws)
            self.sources.append(ws)
        book, _ = synthetic_package(self.root / 'book')
        self.cli('ingest-framework', book, workspace=self.sources[0])
        rows = [self.read(ws) for ws in self.sources]
        self.manifest = dict(schema_version=1, batch_id='synthetic-batch', sources=[dict(
            workspace=str(ws), source_id=row['source']['source_id'], revision=row['revision'], section_ids=['comments'],
            candidate_ids=[row['candidates'][0]['candidate_id']], view=dict(kind='selected', run_id=None))
            for ws, row in zip(self.sources, rows)], framework=dict(workspace=str(self.sources[0]), sha256=rows[0]['frameworks'][0]['sha256']),
            issues=[dict(issue_id='issue-1', title='合成条件讨论', rule_id='rule-1',
                support=[dict(source_id=rows[0]['source']['source_id'], candidate_id=rows[0]['candidates'][0]['candidate_id'])],
                counter=[dict(source_id=rows[1]['source']['source_id'], candidate_id=rows[1]['candidates'][0]['candidate_id'])],
                rationale='人工预填示范，非主动发现。', after=dict(requirement='先核实资料，再决定是否补充。'), unknowns=['正式效力未知'])])
        self.manifest_path = self.root / 'manifest.json'

    def cli(self, *args, workspace=None, ok=True):
        result = subprocess.run([sys.executable, '-m', 'reviewproto', *map(str, args), '--workspace', str(workspace or self.batch)],
                                capture_output=True, encoding='utf-8', errors='replace')
        self.assertEqual(result.returncode, 0 if ok else 2, result.stdout + result.stderr)
        return result

    def read(self, ws=None):
        return json.loads(((ws or self.batch) / 'state.json').read_text(encoding='utf-8'))

    def build(self):
        self.manifest_path.write_bytes(encoded(self.manifest))
        self.cli('batch-build', self.manifest_path)
        return self.read()

    def test_build_selected_multi_source_package_without_mutating_sources_or_private_derivatives(self):
        before = {p: p.read_bytes() for ws in self.sources for p in ws.rglob('*') if p.is_file()}
        state = self.build()
        self.assertEqual(len(state['sources']), 2)
        self.assertEqual(state['sources'][0]['scores'][0]['raw_value'], ' 4.00 ')
        self.assertEqual(state['sources'][0]['sections'][0]['visibility'], 'visibility_unknown')
        self.assertEqual(state['issues'][0]['origin'], 'manual')
        self.assertEqual(state['framework']['authority'], 'unconfirmed')
        self.assertEqual(state['issues'][0]['evidence_scope'], 'baseline_only')
        self.assertIn('合成条件讨论', (self.batch / 'report.html').read_text(encoding='utf-8'))
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data, str(path))
        for path in self.batch.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'PRIVATE-SYNTHETIC-DO-NOT-COPY', path.read_bytes(), str(path))
        self.assertEqual(self.build(), state)

    def patch(self, state):
        return dict(schema_version=1, batch_id=state['batch_id'], base_revision=state['revision'], actor='synthetic-editor',
                    reason='人工合成审核', package_sha256=state['package_sha256'], decisions=[
                        dict(issue_id='issue-1', decision_type='case_decision', case_source_id=state['sources'][0]['source']['source_id'], action='keep', reason='本案无需强制补充'),
                        dict(issue_id='issue-1', decision_type='framework_proposal_review', case_source_id=None, action='need_material', reason='通用要求须另补依据')])

    def apply(self, payload, ok=True):
        patch = self.root / 'decision.json'
        patch.write_bytes(encoded(payload))
        return self.cli('batch-apply', patch, ok=ok)

    def test_decisions_apply_recover_idempotence_history_conflict_and_atomic_rejection(self):
        state = self.build()
        payload = self.patch(state)
        self.apply(payload)
        saved = self.read()
        self.assertEqual([d['decision_type'] for d in saved['decisions']], ['case_decision', 'framework_proposal_review'])
        self.assertEqual(saved['revision'], state['revision'] + 1)
        self.apply(payload)
        self.assertEqual(self.read(), saved)
        for name in ('state.json', 'report.html'):
            (self.batch / name).unlink()
        self.cli('batch-recover')
        self.assertEqual(self.read(), saved)
        stale_revision = copy.deepcopy(payload)
        stale_revision['reason'] = '不同的新决定'
        self.assertIn('E_BATCH_REVISION', self.apply(stale_revision, ok=False).stderr)
        invalid = self.patch(saved)
        invalid['decisions'][1]['action'] = 'publish'
        self.apply(invalid, ok=False)
        invalid_case = self.patch(saved)
        invalid_case['decisions'][0]['case_source_id'] = 'unrelated-source'
        self.assertIn('E_BATCH_CASE_SCOPE', self.apply(invalid_case, ok=False).stderr)
        invalid_case = self.patch(saved)
        invalid_case['decisions'][1]['case_source_id'] = saved['sources'][0]['source']['source_id']
        self.assertIn('E_BATCH_CASE_SCOPE', self.apply(invalid_case, ok=False).stderr)
        self.cli('batch-recover')
        self.assertEqual(self.read(), saved)
        later = self.patch(saved)
        later['decisions'] = [dict(issue_id='issue-1', decision_type='case_decision', case_source_id=saved['sources'][0]['source']['source_id'], action='defer', reason='保留历史，暂缓')]
        self.apply(later)
        reopened = self.read()
        self.assertEqual(len(reopened['decisions']), 3)
        self.assertEqual(reopened['decisions'][0]['action'], 'keep')
        self.assertEqual(reopened['decisions'][2]['action'], 'defer')

    def correct_source(self):
        source = self.sources[0]
        cid = self.manifest['sources'][0]['candidate_ids'][0]
        self.cli('export-template', '--candidate', cid, '--output', str(source / 'correction.json'), workspace=source)
        patch = json.loads((source / 'correction.json').read_text(encoding='utf-8'))
        patch.update(actor='synthetic-corrector', reason='普通观点表单纠正')
        patch['edits'][0]['fields'].update(object='资料范围', status='needs_review')
        (source / 'correction.json').write_bytes(encoded(patch))
        self.cli('apply', source / 'correction.json', workspace=source)

    def test_corrected_source_marks_old_package_stale_and_refresh_preserves_decisions_and_evidence(self):
        initial = self.build()
        self.apply(self.patch(initial))
        saved = self.read()
        self.correct_source()
        self.cli('batch-recover')
        stale = self.read()
        self.assertEqual(stale['material_status'], 'needs_refresh')
        self.assertEqual(stale['decisions'][0]['validity'], 'needs_revalidation')
        self.assertEqual(stale['sources'][0]['candidates'], initial['sources'][0]['candidates'])
        new_attempt = self.patch(stale)
        new_attempt['reason'] = '不能基于旧包新增决定'
        self.assertIn('E_BATCH_STALE', self.apply(new_attempt, ok=False).stderr)
        self.manifest['sources'][0]['revision'] = self.read(self.sources[0])['revision']
        refreshed = self.build()
        self.assertEqual(refreshed['material_status'], 'current')
        self.assertEqual(len(refreshed['decisions']), 2)
        self.assertEqual(refreshed['decisions'][0]['decision_id'], saved['decisions'][0]['decision_id'])
        self.assertEqual(refreshed['decisions'][0]['validity'], 'needs_revalidation')
        self.assertEqual(refreshed['sources'][0]['candidates'][0]['value']['object'], '资料范围')
        self.assertEqual(refreshed['package_history'][0]['sources'], initial['sources'])
        self.assertIn('needs_revalidation', (self.batch / 'report.html').read_text(encoding='utf-8'))

    @unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
    def test_browser_checks_evidence_corrects_original_and_downloads_decisions_for_apply_and_reopen(self):
        from playwright.sync_api import sync_playwright
        self.build()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
            page = browser.new_page(offline=True, accept_downloads=True)
            errors, external = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith('file:') else None)
            page.goto((self.batch / 'report.html').as_uri())
            self.assertIn(' 4.00 ', page.locator('body').inner_text())
            page.get_by_role('link', name=self.manifest['sources'][0]['candidate_ids'][0], exact=True).click()
            self.assertIn('资料不足，应说明局限。', page.locator('body').inner_text())
            self.assertIn('合成 条件', page.locator('body').inner_text())
            page.get_by_role('link', name='在原工作区纠正观点').first.click()
            page.locator('#candidate').select_option(self.manifest['sources'][0]['candidate_ids'][0])
            page.locator('#object').fill('页面纠正资料范围')
            page.locator('#actor').fill('browser-corrector')
            page.locator('#reason').fill('合成浏览器原工作区纠正')
            with page.expect_download() as download:
                page.locator('#download').click()
            correction = self.root / 'browser-correction.json'
            download.value.save_as(correction)
            self.cli('apply', correction, workspace=self.sources[0])
            self.cli('batch-recover')
            page.goto((self.batch / 'report.html').as_uri())
            self.assertIn('needs_refresh', page.locator('#material-status').inner_text())
            self.manifest['sources'][0]['revision'] = self.read(self.sources[0])['revision']
            self.build()
            page.reload()
            page.locator('#actor').fill('browser-reviewer')
            page.locator('#reason').fill('合成条款讨论')
            page.locator('#decision-type').select_option('case_decision')
            page.locator('#case-source').select_option(self.manifest['sources'][0]['source_id'])
            page.locator('#action').select_option('keep')
            page.locator('#decision-reason').fill('本案保留')
            page.locator('#queue').click()
            page.locator('#decision-type').select_option('framework_proposal_review')
            page.locator('#action').select_option('need_material')
            page.locator('#decision-reason').fill('通用条款待补依据')
            page.locator('#queue').click()
            with page.expect_download() as download:
                page.locator('#download').click()
            saved = self.root / 'browser-decisions.json'
            download.value.save_as(saved)
            self.assertIn('尚未应用', page.locator('#save-status').inner_text())
            self.assertEqual(self.read()['decisions'], [])
            self.cli('batch-apply', saved)
            self.cli('batch-recover')
            page.reload()
            self.assertEqual(page.locator('.saved-decision').count(), 2)
            self.assertEqual(self.read()['decisions'][0]['case_source_id'], self.manifest['sources'][0]['source_id'])
            self.assertIn('本案保留', page.locator('.saved-decision').first.inner_text())
            self.assertIn('通用条款待补依据', page.locator('.saved-decision').last.inner_text())
            self.assertEqual(errors, [])
            self.assertEqual(external, [])
            browser.close()

    def test_duplicate_copies_do_not_increase_support_and_invalid_inputs_leave_saved_package_unchanged(self):
        state = self.build()
        copied = self.root / 'copied-workspace'
        shutil.copytree(self.sources[0], copied)
        duplicate = copy.deepcopy(self.manifest['sources'][0])
        duplicate['workspace'] = str(copied)
        self.manifest['sources'].append(duplicate)
        self.assertEqual(self.build(), state)
        for change in (
            lambda m: m['sources'][0].update(source_id='0' * 64),
            lambda m: m['sources'][0].update(revision=True),
            lambda m: m['sources'][0].update(section_ids=['private']),
            lambda m: m['issues'][0]['support'][0].update(candidate_id='unselected-candidate'),
            lambda m: m['issues'][0].update(after={'authority': 'approved'}),
            lambda m: m['framework'].update(sha256='0' * 64),
            lambda m: m['sources'][0]['view'].update(kind='all-runs'),
            lambda m: m['sources'][0]['view'].update(kind='effective'),
        ):
            manifest = copy.deepcopy(self.manifest)
            change(manifest)
            self.manifest_path.write_bytes(encoded(manifest))
            failed = self.cli('batch-build', self.manifest_path, ok=False)
            self.assertNotIn(str(self.root), failed.stderr)
            self.assertNotIn('PRIVATE-SYNTHETIC', failed.stderr)
            self.cli('batch-recover')
            self.assertEqual(self.read(), state)
        self.manifest_path.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
        self.cli('batch-build', self.manifest_path, ok=False)
        self.cli('batch-recover')
        self.assertEqual(self.read(), state)

    def test_analysis_append_is_bound_idempotent_and_cannot_replace_manual_history(self):
        state = self.build()
        self.apply(self.patch(state))
        saved = self.read()
        issue = copy.deepcopy(self.manifest['issues'][0])
        issue['issue_id'] = 'analysis-issue-1'
        payload = dict(schema_version=1, batch_id=saved['batch_id'], base_revision=saved['revision'], package_sha256=saved['package_sha256'],
                       run_id='synthetic-analysis-1', provenance='synthetic-frozen-response; no model invocation', issues=[issue])
        path = self.root / 'analysis.json'
        path.write_bytes(encoded(payload))
        self.cli('batch-append-analysis', path)
        appended = self.read()
        self.assertEqual([i['issue_id'] for i in appended['issues']], ['issue-1', 'analysis-issue-1'])
        self.assertEqual(appended['issues'][1]['origin'], 'analysis_candidate')
        self.assertEqual(appended['decisions'][0]['decision_id'], saved['decisions'][0]['decision_id'])
        self.assertEqual(appended['analysis_runs'][0]['run_id'], 'synthetic-analysis-1')
        self.cli('batch-append-analysis', path)
        self.assertEqual(self.read(), appended)
        payload['issues'][0]['title'] = 'same-run-conflict'
        path.write_bytes(encoded(payload))
        self.assertIn('E_BATCH_RUN_CONFLICT', self.cli('batch-append-analysis', path, ok=False).stderr)
        self.cli('batch-recover')
        self.assertEqual(self.read(), appended)

    def test_changed_source_and_foreign_database_are_rejected_and_linked_projection_cannot_escape(self):
        state = self.build()
        frozen_source = self.sources[0] / 'source.json'
        original = frozen_source.read_bytes()
        frozen_source.write_bytes(original + b' ')
        self.manifest_path.write_bytes(encoded(self.manifest))
        failed = self.cli('batch-build', self.manifest_path, ok=False)
        self.assertIn('E_SOURCE_CHANGED', failed.stderr)
        self.assertNotIn(str(self.root), failed.stderr)
        self.cli('batch-recover')
        self.assertEqual(self.read()['material_status'], 'needs_refresh')
        frozen_source.write_bytes(original)
        self.cli('batch-recover')
        self.assertEqual(self.read(), state)
        outside_source = self.root / 'source-bytes.json'
        outside_source.write_bytes(original)
        frozen_source.unlink()
        try:
            frozen_source.symlink_to(outside_source)
        except OSError:
            frozen_source.write_bytes(original)
            self.skipTest('host cannot create symlinks')
        self.assertIn('E_BATCH_LINK', self.cli('batch-build', self.manifest_path, ok=False).stderr)
        frozen_source.unlink()
        frozen_source.write_bytes(original)
        foreign = self.root / 'foreign'
        foreign.mkdir()
        import sqlite3
        with closing(sqlite3.connect(foreign / 'review.sqlite3')) as db:
            db.execute('CREATE TABLE unrelated (id INTEGER)')
            db.commit()
        before = (foreign / 'review.sqlite3').read_bytes()
        self.manifest['sources'][0]['workspace'] = str(foreign)
        self.manifest_path.write_bytes(encoded(self.manifest))
        self.assertIn('E_BATCH_SOURCE', self.cli('batch-build', self.manifest_path, ok=False).stderr)
        self.assertEqual((foreign / 'review.sqlite3').read_bytes(), before)
        outside = self.root / 'outside.html'
        outside.write_text('MUST-NOT-CHANGE', encoding='utf-8')
        projection = self.batch / 'report.html'
        projection.unlink()
        try:
            projection.symlink_to(outside)
        except OSError:
            self.skipTest('host cannot create symlinks')
        self.assertIn('E_BATCH_LINK', self.cli('batch-recover', ok=False).stderr)
        self.assertEqual(outside.read_text(encoding='utf-8'), 'MUST-NOT-CHANGE')
        self.assertIn('E_BATCH_LINK', self.apply(self.patch(state), ok=False).stderr)
        self.assertEqual(self.read(), state)

    def test_explicit_run_keeps_human_correction_and_split_requires_explicit_reselection(self):
        ws = self.sources[0]
        original = self.read(ws)
        candidate = original['candidates'][0]
        section = original['sections'][0]
        for run in ('run-one', 'run-two'):
            payload = dict(schema_version=1, source_id=original['source']['source_id'], run_id=run, extractor='synthetic-fixed-provider',
                model='no-network', config={}, sections=[dict(section_id='comments', text_sha256=digest(section['text'].encode()))],
                candidates=[dict(section_id='comments', evidence=candidate['evidence'])])
            path = self.root / f'{run}.json'
            path.write_bytes(encoded(payload))
            self.cli('ingest-candidates', path, workspace=ws)
        current = self.read(ws)
        selected = next(c for c in current['candidates'] if c.get('run_id') == 'run-one')
        self.manifest['sources'][0].update(candidate_ids=[selected['candidate_id']], revision=current['revision'], view=dict(kind='run', run_id='run-one'))
        self.manifest['issues'][0]['support'][0]['candidate_id'] = selected['candidate_id']
        self.correct_source()
        self.manifest['sources'][0]['revision'] = self.read(ws)['revision']
        state = self.build()
        self.assertEqual(len(state['sources'][0]['candidates']), 1)
        self.assertEqual(state['sources'][0]['candidates'][0]['value']['object'], '资料范围')
        source_state = self.read(ws)
        split = dict(schema_version=1, source_id=source_state['source']['source_id'], base_revision=source_state['revision'],
            actor='synthetic-splitter', reason='拆分后不能静默沿用旧父项', edits=[], creates=[dict(candidate_id='human-child-one', section_id='comments',
                parent_ids=[selected['candidate_id']], replaces=[selected['candidate_id']], fields=dict(status='needs_review', evidence=selected['evidence']))])
        path = self.root / 'split.json'
        path.write_bytes(encoded(split))
        self.cli('apply', path, workspace=ws)
        self.manifest['sources'][0]['revision'] = self.read(ws)['revision']
        self.manifest_path.write_bytes(encoded(self.manifest))
        self.assertIn('E_BATCH_RESELECT_REQUIRED', self.cli('batch-build', self.manifest_path, ok=False).stderr)
        self.manifest['sources'][0].update(candidate_ids=['human-child-one'], view=dict(kind='selected', run_id=None))
        self.manifest['issues'][0]['support'][0]['candidate_id'] = 'human-child-one'
        refreshed = self.build()
        self.assertEqual(refreshed['sources'][0]['candidates'][0]['value']['parent_ids'], [selected['candidate_id']])

    def test_concurrent_decisions_at_same_revision_allow_one_writer(self):
        from concurrent.futures import ThreadPoolExecutor
        state = self.build()
        paths = []
        for index in range(2):
            payload = self.patch(state)
            payload['reason'] = f'concurrent-synthetic-{index}'
            path = self.root / f'concurrent-{index}.json'
            path.write_bytes(encoded(payload))
            paths.append(path)
        def apply_once(path):
            return subprocess.run([sys.executable, '-m', 'reviewproto', 'batch-apply', str(path), '--workspace', str(self.batch)], capture_output=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply_once, paths))
        self.assertEqual(sorted(r.returncode for r in results), [0, 2])
        self.assertIn(b'E_BATCH_REVISION', next(r for r in results if r.returncode == 2).stderr)
        self.cli('batch-recover')
        self.assertEqual(self.read()['revision'], state['revision'] + 1)
        self.assertEqual(len(self.read()['decisions']), 2)
