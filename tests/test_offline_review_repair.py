"""Synthetic offline conversion, optional field and ordinary review acceptance."""
from contextlib import closing
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

from experiments import extract_local as adapter
from reviewproto.batch import source_state
from reviewproto.cli import main as cli
from reviewproto.core import ReviewError, digest, validate_candidate
from reviewproto.replay_grounding import replay
from reviewproto.review_links import main_quote_overlaps, text_range, render_overlap_panel
from reviewproto.store import Workspace, encoded
from reviewproto.understanding import current_views
import test_batch_flow as batch_fixture

CHROME = Path(os.environ.get('REVIEW_BROWSER_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))


class OfflineRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'workspace'
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)

    def source(self, text='建议补图。若无条件则说明边界。', private=False):
        source = self.root / 'source.json'
        source.write_bytes(encoded(dict(schema_version=1, scores=[], sections=[dict(section_id='comments',
            label='作者不可见' if private else '评审意见', text=text,
            visibility='internal_only' if private else 'visibility_unknown')])))
        with closing(Workspace(self.path)) as ws:
            return ws.run(source, 'synthetic', 'json')

    def extraction(self, text, **changes):
        attrs = {key: [] if key in adapter.LIST_ATTRIBUTES else 'unknown' for key in adapter.ATTRIBUTES['opinion']}
        attrs.update(action='补图', requirement_strength='recommended', branch_conditions=['若无条件'], branch_actions=['说明边界'])
        attrs.update(changes)
        return Obj(extraction_class='opinion', extraction_text=text, attributes=attrs, char_interval=None)

    def fixture(self, *, extra_errors=(), status='complete', rejected=False, private=False, text=None, config_changes=None, empty=False):
        state = self.source(private=private) if text is None else self.source(text, private)
        section = state['sections'][0]
        raw = self.extraction(section['text'])
        document = Obj(extractions=[] if empty else [raw])
        candidates, _, errors = adapter.convert(document, section, section['text'], 0, 'old-')
        payload = dict(schema_version=1, source_id=state['source']['source_id'], run_id='old-run', extractor='synthetic-grounding-v3',
            model='deepseek-flash', status=status, errors=errors + list(extra_errors),
            sections=[dict(section_id='comments', text_sha256=digest(section['text'].encode()))],
            config=dict(window_chars=600, protocol='v3', model_requests=0, external_model_requests=0), candidates=candidates + ([None] if rejected else []))
        payload['config'].update(config_changes or {})
        folder = self.path / 'model-artifacts/old-run'
        folder.mkdir(parents=True)
        scope = dict(section_id='comments', window_start=0, window_end=len(section['text']))
        grounding = [dict(scope=scope, extractions=[] if empty else [dict(**{'class': 'opinion'}, text=raw.extraction_text, attributes=raw.attributes, interval=None)])]
        windows = [dict(**scope, status='converted', window_kind='paragraph_window', candidates=len(candidates), errors=errors)]
        for name, value in (('candidates.json', payload), ('grounding.json', grounding), ('windows.json', windows)):
            (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        with closing(Workspace(self.path)) as ws:
            imported = ws.import_extractions(input_path=folder / 'candidates.json')
        return imported, folder, payload

    def test_single_pair_is_explicit_opt_in_and_machine_semantics_remain_unknown(self):
        state = self.source()
        section = state['sections'][0]
        document = Obj(extractions=[self.extraction(section['text'])])
        legacy, _, errors = adapter.convert(document, section, section['text'], 0, 'old-')
        self.assertIn('E_MODEL_BRANCH_PAIRING', errors)
        self.assertNotIn('conditional_actions', legacy[0])
        converted, _, errors = adapter.convert(document, section, section['text'], 0, 'new-', policy=adapter.OFFLINE_SINGLE_PAIR)
        candidate = converted[0]
        self.assertEqual(errors, [])
        self.assertEqual(candidate['action'], '补图')
        self.assertEqual(candidate['requirement_strength'], 'unknown')
        self.assertEqual(candidate['alternatives'], [])
        relation = candidate['conditional_actions'][0]
        self.assertEqual((relation['condition'], relation['action'], relation['meaning']), ('若无条件', '说明边界', 'unknown'))
        self.assertTrue(relation['evidence_indices'])
        self.assertIn('conditional_action_scope_requires_review', candidate['review_flags'])

    def test_malformed_ambiguous_paraphrased_and_cross_opinion_pairs_stay_errors(self):
        state = self.source('建议补图。若无条件则说明边界。若无条件则延期。')
        section = state['sections'][0]
        cases = [self.extraction(section['text']),
            self.extraction('建议补图。', branch_conditions=['若无条件'], branch_actions=['说明边界']),
            self.extraction(section['text'], branch_conditions=['若无条件'], branch_actions=['说明情况']),
            self.extraction(section['text'], branch_actions=[]),
            self.extraction(section['text'], branch_conditions='若无条件')]
        for extraction in cases:
            with self.subTest(attributes=extraction.attributes):
                candidates, _, errors = adapter.convert(Obj(extractions=[extraction]), section, section['text'], 0, 'bad-', policy=adapter.OFFLINE_SINGLE_PAIR)
                self.assertTrue(errors)
                self.assertFalse(any(c.get('conditional_actions') for c in candidates))

    def test_core_optional_field_literal_support_and_machine_guard(self):
        state = self.source()
        original = copy.deepcopy(state['candidates'][0])
        self.assertNotIn('conditional_actions', original)
        validate_candidate(original, state, allow_pending=True)
        self.assertNotIn('conditional_actions', original)
        valid = copy.deepcopy(original)
        valid['conditional_actions'] = [dict(condition='若无条件', action='说明边界', meaning='unknown', provenance='explicit', evidence_indices=[0])]
        validate_candidate(valid, state, allow_pending=True)
        for changes in (dict(condition='改写条件'), dict(action='不在引文'), dict(evidence_indices=[]),
                        dict(evidence_indices=[100]), dict(condition='unknown'), dict(meaning='wrong'), dict(extra='x')):
            bad = copy.deepcopy(valid); bad['conditional_actions'][0].update(changes)
            with self.assertRaises(ReviewError):
                validate_candidate(bad, state, allow_pending=True)
        unknown = copy.deepcopy(valid)
        unknown['conditional_actions'][0].update(condition='unknown', action='unknown', provenance='unknown')
        validate_candidate(unknown, state, allow_pending=True)
        machine = copy.deepcopy(valid)
        machine.update(origin='model_candidate')
        machine['conditional_actions'][0]['meaning'] = 'known'
        with self.assertRaisesRegex(ReviewError, 'E_MACHINE_CONDITIONAL_ACTION'):
            validate_candidate(machine, state, allow_pending=True)

    def test_explicit_offline_policy_keeps_two_branch_and_either_or_results(self):
        state = self.source('若条件甲则做甲，若条件乙则做乙。补图或者补表。')
        section = state['sections'][0]
        cases = [self.extraction('若条件甲则做甲，若条件乙则做乙。', action='unknown',
                 branch_conditions=['若条件甲','若条件乙'], branch_actions=['做甲','做乙']),
                 self.extraction('补图或者补表。', action='unknown', branch_relation='either_or',
                 branch_conditions=[],branch_actions=['补图','补表'])]
        for extraction in cases:
            document = Obj(extractions=[extraction])
            old = adapter.convert(document, section, section['text'], 0, 'same-')
            new = adapter.convert(document, section, section['text'], 0, 'same-', policy=adapter.OFFLINE_SINGLE_PAIR)
            self.assertEqual(new, old)
            self.assertEqual(len(new[0][0]['alternatives'][0]['branches']), 2)

    def test_replay_cli_is_readonly_then_existing_import_recover_keeps_both_runs(self):
        state, folder, original = self.fixture()
        snapshots = {p: p.read_bytes() for p in self.path.rglob('*') if p.is_file()}
        with patch.object(Workspace, '__init__', side_effect=AssertionError('write initializer forbidden')), \
             patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')), \
             patch('os.getenv', side_effect=AssertionError('secret read forbidden')), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(cli(['replay-grounding', '--workspace', str(self.path), '--from-run', 'old-run', '--run-id', 'new-run']), 0)
        self.assertIn('model_requests=0', output.getvalue())
        for path, raw in snapshots.items():
            self.assertEqual(path.read_bytes(), raw, str(path))
        payload = json.loads((self.path / 'model-artifacts/new-run/candidates.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['config']['model_requests'], 0)
        self.assertEqual(payload['config']['original_payload_sha256'], digest(encoded(original)))
        self.assertEqual(payload['config']['original_payload_file_sha256'], digest((folder / 'candidates.json').read_bytes()))
        self.assertNotEqual(payload['config']['original_payload_sha256'], payload['config']['original_payload_file_sha256'])
        self.assertEqual(payload['errors'], [])
        with closing(Workspace(self.path)) as ws:
            imported = ws.import_extractions(input_path=self.path / 'model-artifacts/new-run/candidates.json')
            reopened = ws.recover()
        self.assertEqual([r['status'] for r in reopened['extraction_runs']], ['partial', 'complete'])
        self.assertEqual(reopened['extraction_runs'][0], state['extraction_runs'][0])
        new = [c for c in reopened['candidates'] if c.get('run_id') == 'new-run'][0]
        self.assertEqual(new['status'], 'pending_review')
        self.assertEqual(new['paper_verification'], 'not_checked')
        self.assertEqual(new['standard_alignment'], 'pending_comparison')
        self.assertEqual(new['conditional_actions'][0]['meaning'], 'unknown')
        with self.assertRaisesRegex(ReviewError, 'E_REPLAY_RUN_EXISTS'):
            replay(self.path, 'old-run', 'new-run')

    def test_unresolved_upstream_errors_rejections_and_failed_state_survive(self):
        self.fixture(extra_errors=['E_USAGE_UNKNOWN_STOP'], rejected=True)
        result = replay(self.path, 'old-run', 'new-run')
        self.assertIn('E_USAGE_UNKNOWN_STOP', result['errors'])
        self.assertIn('E_REPLAY_UPSTREAM_REJECTED', result['errors'])
        self.assertNotIn('E_MODEL_BRANCH_PAIRING', result['errors'])
        self.assertEqual(result['status'], 'complete')  # Core derives partial.
        with closing(Workspace(self.path)) as ws:
            imported = ws.import_extractions(input_path=self.path / 'model-artifacts/new-run/candidates.json')
        self.assertEqual(imported['extraction_runs'][-1]['status'], 'partial')

    def test_failed_upstream_is_not_upgraded(self):
        self.fixture(status='failed')
        result = replay(self.path, 'old-run', 'new-run')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('E_REPLAY_UPSTREAM_FAILED', result['errors'])

    def test_missing_windows_or_grounding_stay_failed_not_empty_success(self):
        _, folder, _ = self.fixture()
        (folder / 'windows.json').write_bytes(encoded([]))
        result = replay(self.path, 'old-run', 'missing-windows')
        self.assertIn('E_REPLAY_WINDOW_MISSING', result['errors'])
        self.assertEqual(result['status'], 'failed')
        (folder / 'windows.json').write_bytes(encoded([dict(section_id='comments', window_start=0,
            window_end=len(source_state(self.path)['sections'][0]['text']), status='converted', errors=['E_MODEL_BRANCH_PAIRING'])]))
        (folder / 'grounding.json').write_bytes(encoded([]))
        result = replay(self.path, 'old-run', 'missing-grounding')
        self.assertIn('E_REPLAY_GROUNDING_MISSING', result['errors'])
        self.assertEqual(result['status'], 'failed')

    def test_window_only_upstream_error_is_preserved_even_if_payload_omitted_it(self):
        _, folder, _ = self.fixture()
        windows=json.loads((folder/'windows.json').read_bytes())
        windows[0]['errors'].append('E_UPSTREAM_WINDOW_ONLY')
        (folder/'windows.json').write_bytes(encoded(windows))
        result=replay(self.path,'old-run','window-error')
        self.assertIn('E_UPSTREAM_WINDOW_ONLY',result['errors'])

    def test_legitimate_empty_grounding_stays_zero_candidates(self):
        self.fixture(empty=True)
        result=replay(self.path,'old-run','empty-replay')
        self.assertEqual((result['status'],result['errors'],result['candidates']),('complete',[],[]))
        with closing(Workspace(self.path)) as ws:
            saved=ws.import_extractions(input_path=self.path/'model-artifacts/empty-replay/candidates.json')
        self.assertEqual([r['status'] for r in saved['extraction_runs']],['zero_candidates','zero_candidates'])

    def test_wrong_payload_hash_illegal_window_interval_and_shape_refuse(self):
        _, folder, _ = self.fixture()
        path = folder / 'candidates.json'; raw = path.read_bytes()
        value = json.loads(raw); value['model'] = 'wrong-model'; path.write_bytes(encoded(value))
        with self.assertRaisesRegex(ReviewError, 'E_REPLAY_PAYLOAD_HASH'):
            replay(self.path, 'old-run', 'wrong-hash')
        path.write_bytes(raw)
        grounding = json.loads((folder / 'grounding.json').read_bytes())
        for mutation in ('scope', 'interval', 'shape'):
            bad = copy.deepcopy(grounding)
            if mutation == 'scope': bad[0]['scope']['window_end'] += 1
            elif mutation == 'interval': bad[0]['extractions'][0]['interval'] = [0, 10000]
            else: bad[0]['extractions'][0]['attributes'] = []
            (folder / 'grounding.json').write_bytes(encoded(bad))
            with self.assertRaises(ReviewError):
                replay(self.path, 'old-run', 'invalid-' + mutation)
        (folder / 'grounding.json').write_bytes(encoded(grounding))
        with self.assertRaisesRegex(ReviewError, 'E_REPLAY_RUN_ID'):
            replay(self.path, 'old-run', '../escape')

    def test_private_sections_refuse(self):
        self.fixture(private=True)
        with self.assertRaisesRegex(ReviewError, 'E_REPLAY_PRIVATE'):
            replay(self.path, 'old-run', 'new-run')

    def test_historical_artifact_hash_binding_is_checked_when_present(self):
        self.fixture(config_changes=dict(grounding_sha256='0'*64))
        with self.assertRaisesRegex(ReviewError, 'E_REPLAY_ARTIFACT_HASH'):
            replay(self.path, 'old-run', 'new-run')

    def test_artifact_links_and_existing_output_are_refused(self):
        _, folder, _ = self.fixture()
        target = folder / 'grounding.json'
        with patch('reviewproto.batch.linklike', side_effect=lambda p: Path(p) == target):
            with self.assertRaisesRegex(ReviewError, 'E_BATCH_LINK'):
                replay(self.path, 'old-run', 'linked-run')
        (self.path / 'model-artifacts/existing').mkdir()
        with self.assertRaisesRegex(ReviewError, 'E_REPLAY_RUN_EXISTS'):
            replay(self.path, 'old-run', 'existing')

    def test_quote_overlap_uses_main_evidence_only_and_is_bounded(self):
        def candidate(cid, start, end, sid='comments', **changes):
            value = dict(candidate_id=cid, section_id=sid, status='needs_review', direction='unknown',
                evidence=[dict(source_id='synthetic-source',section_id=sid,start=start, end=end, quote='x' * (end-start)), dict(start=5, end=6, quote='x')])
            value.update(changes)
            return dict(value=value)
        source = dict(source=dict(source_id='synthetic-source'), revision=1, workspace=str(self.path),
            sections=[dict(section_id='comments', visibility='visibility_unknown'),dict(section_id='private',visibility='internal_only')],
            candidates=[candidate('wide', 0, 20), candidate('narrow', 2, 10, direction='negative'),
                        candidate('crossing', 18, 30), candidate('private', 2, 10, sid='private'),
                        candidate('withdrawn', 2, 10, status='withdrawn')])
        pairs, limited = main_quote_overlaps(source)
        self.assertFalse(limited)
        self.assertEqual([(p['left']['candidate_id'],p['right']['candidate_id']) for p in pairs], [('wide','narrow')])
        source['candidates'].append(candidate('foreign',1,15,evidence=[dict(source_id='other-source',section_id='comments',start=1,end=15,quote='foreign')]))
        self.assertEqual(len(main_quote_overlaps(source)[0]),1)
        source['candidates'] = [candidate(str(i), 0, 20) for i in range(10000)]
        pairs, limited = main_quote_overlaps(source)
        self.assertEqual(len(pairs), 200); self.assertTrue(limited)
        self.assertIn('仅展示前 200 对', render_overlap_panel(source))
        self.assertFalse(text_range(dict(quote='；。——😀')))
        self.assertTrue(text_range(dict(quote='；要求A。')))


class AnalysisProjectionTests(unittest.TestCase):
    setUp = batch_fixture.BatchFlowTests.setUp
    cli = batch_fixture.BatchFlowTests.cli
    read = batch_fixture.BatchFlowTests.read
    build = batch_fixture.BatchFlowTests.build

    def test_human_conditional_action_refreshes_binding_and_reaches_fixed_analysis_projection(self):
        from reviewproto.batch import BatchWorkspace
        from reviewproto.batch_discovery import input_binding, local_issues
        initial = self.build()
        relation = dict(condition='资料不足',action='说明局限',meaning='unknown',provenance='explicit',evidence_indices=[0])
        with closing(Workspace(self.sources[0])) as source:
            patch_value = source.review_template()
            patch_value.update(actor='synthetic-agent',reason='Synthetic relationship',edits=patch_value['edits'][:1])
            patch_value['edits'][0]['fields']['conditional_actions']=[relation]
            source.apply(patch_value)
        with closing(BatchWorkspace(self.batch)) as ws:
            self.assertEqual(ws.state()['material_status'],'needs_refresh')
            state = ws.refresh()
            self.assertNotEqual(initial['package_sha256'],state['package_sha256'])
            self.assertNotEqual(input_binding(initial),input_binding(state))
            self.assertEqual(state['sources'][0]['candidates'][0]['value']['conditional_actions'],[relation])
            analysis=dict(input_sha256=input_binding(state),calls=[],errors=[],model_requests=0,config=dict(
                candidate_ids=[],context_chars=10000,max_output_tokens=256,model='synthetic-only',endpoint='http://127.0.0.1:8766/v1'))
            folder=self.root/'analysis';folder.mkdir()
            answer=dict(choices=[dict(finish_reason='stop',message=dict(content='{"issues":[]}'))])
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value=io.BytesIO(encoded(answer))
                self.assertEqual(local_issues(ws,state,[state['framework']['book']['rules'][0]],'synthetic-analysis',folder,analysis),[])
                request=opener.return_value.open.call_args.args[0]
            body=json.loads(request.data)
            projected=json.loads(body['messages'][1]['content'])['opinions'][0]['opinion']
            self.assertEqual(projected['conditional_actions'],[relation])
            self.assertNotIn('scores',projected)
            self.assertEqual(analysis['errors'],[])


@unittest.skipUnless(CHROME.is_file() and importlib.util.find_spec('playwright'), 'local Chrome and Playwright needed')
class ConditionalEditorTests(unittest.TestCase):
    def test_ordinary_condition_action_controls_download_apply_recover_and_reference_protection(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'workspace'
            source = root / 'source.json'; text = '条件甲动作乙。末段。'
            source.write_bytes(encoded(dict(schema_version=1,scores=[],sections=[dict(section_id='comments',label='评审意见',text=text)])))
            with closing(Workspace(path)) as ws:
                initial = ws.run(source, 'synthetic', 'json')
                patch_value = ws.review_template(); patch_value.update(actor='synthetic',reason='Extra evidence fixture')
                full = patch_value['edits'][0]['fields']['evidence'][0]
                patch_value['edits'][0]['fields']['evidence'] += [dict(full,start=7,end=10,quote=text[7:10]),dict(full,start=0,end=7,quote=text[:7])]
                ws.apply(patch_value)
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=str(CHROME),headless=True)
                page=browser.new_page(offline=True,accept_downloads=True,viewport=dict(width=420,height=900))
                errors=[]; page.on('pageerror',lambda e: errors.append(str(e)))
                page.goto((path/'report.html').as_uri())
                page.locator('#add-conditional-action').click()
                row=page.locator('#conditional-actions-rows > fieldset')
                row.locator('input[data-key="condition"]').fill('条件甲')
                row.locator('input[data-key="action"]').fill('动作乙')
                row.locator('select[data-key="provenance"]').select_option('explicit')
                row.locator('input[type="checkbox"]').nth(0).uncheck()
                row.locator('input[type="checkbox"]').nth(2).check()
                page.locator('#evidence-list button').nth(2).click()
                self.assertIn('仍被引用', page.locator('#message').inner_text())
                page.locator('#evidence-list button').nth(1).click()
                fields=json.loads(page.locator('#patch').input_value())['edits'][0]['fields']
                self.assertEqual(fields['conditional_actions'][0]['evidence_indices'],[1])
                page.locator('#actor').fill('synthetic-agent');page.locator('#reason').fill('Ordinary relation controls')
                with page.expect_download() as download:
                    page.locator('#download').click()
                download.value.save_as(root/'patch.json')
                with closing(Workspace(path)) as ws:
                    saved=ws.apply(input_path=root/'patch.json');ws.recover()
                page.goto('about:blank');page.goto((path/'report.html').as_uri())
                self.assertEqual(page.locator('#conditional-actions-rows input[data-key="condition"]').input_value(),'条件甲')
                self.assertEqual(page.locator('#conditional-actions-rows input[data-key="action"]').input_value(),'动作乙')
                self.assertEqual(page.locator('#conditional-actions-rows select[data-key="meaning"]').input_value(),'unknown')
                advanced=json.loads(page.locator('#patch').input_value())
                advanced['edits'][0]['fields']={'object':'局部对象修改'}
                page.locator('#patch').evaluate("e=>e.closest('details').open=true")
                page.locator('#patch').fill(json.dumps(advanced,ensure_ascii=False))
                pending=page.locator('#patch').input_value()
                page.locator('#conditional-actions-rows input[data-key="action"]').fill('未载入不能覆盖')
                self.assertEqual(page.locator('#patch').input_value(),pending)
                page.locator('#import-advanced').click()
                self.assertEqual(page.locator('#conditional-actions-rows input[data-key="action"]').input_value(),'动作乙')
                self.assertEqual(page.locator('#object').input_value(),'局部对象修改')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),420)
                row=page.locator('#conditional-actions-rows > fieldset')
                row.locator('input[type="checkbox"]').nth(0).check()
                row.locator('input[type="checkbox"]').nth(1).uncheck()
                page.locator('#evidence-list button').nth(1).click()
                page.locator('#split-offset').fill('3');page.locator('#split').click()
                split=json.loads(page.locator('#patch').input_value())
                self.assertEqual(len(split['creates']),2)
                self.assertTrue(all(c['fields']['conditional_actions']==[] for c in split['creates']))
                self.assertFalse(errors)
                browser.close()
