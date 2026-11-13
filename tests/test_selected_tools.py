"""Product paths with synthetic evidence, injected scores and approved transport."""
from contextlib import closing
import copy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from lxml import html as html_parser

import test_batch_flow as batches
import test_deepseek_trial as flash
from reviewproto.batch import BatchWorkspace
from reviewproto.batch_retrieval import retrieve, restored, entries
from reviewproto.core import ReviewError, digest
from reviewproto.framework import framework_digest
from reviewproto.store import Workspace, encoded
from reviewproto import approved_extraction as approved
from reviewproto.desktop import Controller
from experiments import deepseek_trial as trial


class RetrievalTests(unittest.TestCase):
    setUp = batches.BatchFlowTests.setUp
    cli = batches.BatchFlowTests.cli
    read = batches.BatchFlowTests.read
    build = batches.BatchFlowTests.build
    correct_source = batches.BatchFlowTests.correct_source
    apply = batches.BatchFlowTests.apply
    patch = batches.BatchFlowTests.patch

    def search(self, run='search-one', **kwargs):
        query = self.root / 'query.txt'
        if not query.exists():
            query.write_text('资料是否充分？', encoding='utf-8')
        model = self.root / 'model'
        model.mkdir(exist_ok=True)
        (model / 'synthetic.onnx').write_bytes(b'synthetic-not-a-model')
        (model / 'tokenizer_config.json').write_bytes(encoded(dict(model_max_length=512)))
        with closing(BatchWorkspace(self.batch)) as ws:
            return retrieve(ws, query_path=query, run_id=run, method='bge', model_path=model,
                score_provider=kwargs.pop('score_provider', lambda query, quotes: [0.9] * len(quotes)), **kwargs)

    def test_product_sidecar_report_idempotence_without_source_or_package_mutation(self):
        before = self.build()
        snapshots = {p: p.read_bytes() for root in [*self.sources, self.batch] for p in root.rglob('*')
                     if p.is_file() and p.name not in {'state.json', 'report.html', 'batch.sqlite3'}}
        with closing(sqlite3.connect(self.batch / 'batch.sqlite3')) as db:
            database_payload = db.execute('SELECT payload FROM state').fetchone()
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            run = self.search()
            again = self.search()
        self.assertEqual(run, again)
        self.assertEqual(len(run['hits']), 2)
        self.assertEqual({h['quote'] for h in run['hits']}, {'资料不足，应说明局限。', '已有充分资料，无需补充。'})
        for path, data in snapshots.items():
            self.assertEqual(path.read_bytes(), data, str(path))
        after = self.read()
        with closing(sqlite3.connect(self.batch / 'batch.sqlite3')) as db:
            self.assertEqual(database_payload, db.execute('SELECT payload FROM state').fetchone())
        for key in ('revision', 'package_sha256', 'decisions', 'issues', 'sources'):
            self.assertEqual(before[key], after[key])
        report = (self.batch / 'report.html').read_text(encoding='utf-8')
        self.assertIn('retrieval-results', report)
        self.assertIn('与本次材料一致', report)
        self.assertIn('本机中文语义(BGE)', report)
        self.assertIn('候选相关性 0.900', report)
        self.assertIn('不表示判断已获确认', report)
        self.assertIn('<summary>运行记录</summary><p>search-one</p>', report)
        self.assertIn('#candidate-' + run['hits'][0]['source_id'] + '-' + run['hits'][0]['candidate_id'], report)
        payload = (self.batch / 'retrieval-runs/search-one.json').read_text(encoding='utf-8')
        for forbidden in ('PRIVATE-SYNTHETIC', 'raw_value', '工作量', 'rule-1'):
            self.assertNotIn(forbidden, payload)
        (self.root / 'query.txt').write_text('不同查询', encoding='utf-8')
        with self.assertRaisesRegex(ReviewError, 'E_RETRIEVAL_RUN_CONFLICT'):
            self.search()
        self.apply(self.patch(after))
        with closing(sqlite3.connect(self.batch / 'batch.sqlite3')) as db:
            self.assertNotIn('retrieval_runs', json.loads(db.execute('SELECT payload FROM state').fetchone()[0]))
        self.cli('batch-recover')
        self.assertEqual(self.read()['retrieval_runs'][0]['validity'], 'current')

    def test_unselected_sentinel_never_enters_encoder(self):
        source = self.root / 'selected-source'
        input_path = self.root / 'selected-input.json'
        input_path.write_bytes(encoded(dict(schema_version=1, scores=[], sections=[dict(section_id='comments',
            label='评审意见', text='😀可见观点。\nUNSELECTED-SENTINEL', visibility='visibility_unknown')])))
        with closing(Workspace(source)) as ws:
            ws.run(input_path, 'synthetic', 'json')
            state = ws.state()
            self.manifest['sources'][0].update(workspace=str(source), source_id=state['source']['source_id'],
                revision=state['revision'], candidate_ids=[state['candidates'][0]['candidate_id']])
        self.manifest['issues'] = []
        self.build()
        score = Mock(side_effect=lambda query, quotes: [0.3] * len(quotes))
        self.search(score_provider=score)
        self.assertEqual(len(score.call_args.args[1]), 2)
        self.assertNotIn('UNSELECTED-SENTINEL', '\n'.join(score.call_args.args[1]))

    def test_repeat_build_rehydrates_sidecars_without_persisting_them(self):
        initial = self.build()
        self.assertEqual(initial['retrieval_runs'], [])
        self.assertEqual(self.build(), initial)
        self.search()
        searched = self.read()
        self.assertEqual(searched['retrieval_runs'][0]['validity'], 'current')
        self.assertEqual(self.build(), searched)
        self.assertEqual(self.build(), searched)
        with closing(BatchWorkspace(self.batch)) as ws:
            self.assertEqual(ws.build(self.manifest), searched)
            saved = json.loads(ws.db.execute('SELECT payload FROM state').fetchone()[0])
        self.assertNotIn('retrieval_runs', saved)
        self.assertEqual(saved['revision'], initial['revision'])
        self.assertEqual(saved['package_sha256'], initial['package_sha256'])

    def test_stale_source_and_bad_sidecar_do_not_become_current(self):
        before = self.build()
        self.search()
        self.correct_source()
        self.cli('batch-recover')
        state = self.read()
        self.assertEqual(state['retrieval_runs'][0]['validity'], 'needs_revalidation')
        self.assertEqual(state['retrieval_runs'][0]['hits'], [])
        self.assertIn('旧结果待重新查找', (self.batch / 'report.html').read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ReviewError, 'E_BATCH_SOURCE_CHANGED'):
            self.search('fresh-run')
        sidecar = self.batch / 'retrieval-runs/search-one.json'
        sidecar.write_text('{broken', encoding='utf-8')
        self.cli('batch-recover')
        self.assertEqual(self.read()['retrieval_runs'][0]['validity'], 'invalid')
        self.assertEqual(before['revision'], self.read()['revision'])

    def test_huge_integer_scores_are_isolated_for_current_and_old_bindings(self):
        self.build()
        self.search()
        path = self.batch / 'retrieval-runs/search-one.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for exponent in (400, 1000):
            for stale in (False, True):
                with self.subTest(exponent=exponent, stale=stale):
                    payload = copy.deepcopy(original)
                    payload['hits'][0]['score'] = 10 ** exponent
                    if stale:
                        payload['input_sha256'] = '0' * 64
                    payload['request_sha256'] = framework_digest({k: payload[k] for k in ('query', 'config', 'input_sha256', 'top_k')})
                    payload.pop('sha256')
                    payload['sha256'] = framework_digest(payload)
                    path.write_bytes(encoded(payload))
                    with closing(BatchWorkspace(self.batch)) as ws:
                        state = ws.state()
                        self.assertEqual(state['retrieval_runs'][0]['validity'], 'invalid')
                        self.assertEqual(ws.recover()['retrieval_runs'][0]['validity'], 'invalid')
                        saved = ws.apply(self.patch(state))
                        self.assertEqual(saved['retrieval_runs'][0]['validity'], 'invalid')
                    self.assertIn('记录不可用', (self.batch / 'report.html').read_text(encoding='utf-8'))

    def test_lexical_label_and_score_display_preserve_full_sidecar_precision(self):
        self.build()
        with closing(BatchWorkspace(self.batch)) as ws:
            query = self.root / 'lexical-query.txt'
            query.write_text('资料', encoding='utf-8')
            run = retrieve(ws, query_path=query, run_id='lexical-one', method='lexical',
                           score_provider=lambda query, quotes: [0.12345678912345678] * len(quotes))
        report = (self.batch / 'report.html').read_text(encoding='utf-8')
        self.assertIn('词面查找', report)
        self.assertIn('候选相关性 0.123', report)
        self.assertNotIn('0.12345678912345678', html_parser.fromstring(report).get_element_by_id('retrieval-results').text_content())
        payload = json.loads((self.batch / 'retrieval-runs/lexical-one.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['hits'][0]['score'], 0.12345678912345678)

    def test_bad_paths_model_and_encoding_fail_without_fallback(self):
        self.build()
        for run_id in ('../escape', 'x/y', 'bad.html', '😀'):
            with self.assertRaisesRegex(ReviewError, 'E_RETRIEVAL_RUN_ID'):
                self.search(run_id)
        with closing(BatchWorkspace(self.batch)) as ws:
            query = self.root / 'query.txt'
            query.write_text('查询', encoding='utf-8')
            with self.assertRaisesRegex(ReviewError, 'E_RETRIEVAL_MODEL_REQUIRED'):
                retrieve(ws, query_path=query, run_id='no-model', method='bge')
        with self.assertRaisesRegex(ReviewError, 'E_RETRIEVAL_ENCODING'):
            self.search('nan-score', score_provider=lambda query, quotes: [float('nan')] * len(quotes))
        self.assertFalse((self.batch / 'retrieval-runs').exists())

    def test_discontinuous_emoji_and_repeated_quotes_stay_separate(self):
        state = self.build()
        source = state['sources'][0]
        source['sections'][0]['text'] = '😀前句。中间。前句。'
        candidate = source['candidates'][0]['value']
        candidate['evidence'] = [dict(start=1, end=4, quote='前句。'), dict(start=7, end=10, quote='前句。')]
        indexed = entries(state)
        self.assertEqual([(e['evidence_index'], e['start'], e['quote']) for e in indexed[:2]], [(0, 1, '前句。'), (1, 7, '前句。')])

    def test_recomputed_corrupt_sidecar_rejected_and_empty_candidates_legal(self):
        self.build()
        self.search()
        path = self.batch / 'retrieval-runs/search-one.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['hits'][0]['quote'] = 'invented'
        payload.pop('sha256')
        payload['sha256'] = framework_digest(payload)
        path.write_bytes(encoded(payload))
        self.cli('batch-recover')
        self.assertEqual(self.read()['retrieval_runs'][0]['validity'], 'invalid')
        with closing(BatchWorkspace(self.batch)) as ws:
            state = ws.state()
            for source in state['sources']:
                source['candidates'] = []
            with patch.object(ws, 'state', return_value=state), patch.object(ws, 'recover', return_value=dict(retrieval_runs=[dict(run_id='empty', hits=[])])):
                result = retrieve(ws, query_path=self.root / 'query.txt', run_id='empty', method='lexical')
            self.assertEqual(result['hits'], [])


class ApprovedProductTests(unittest.TestCase):
    setUp = flash.DeepSeekTrialTests.setUp
    fixture = flash.DeepSeekTrialTests.fixture
    approve = flash.DeepSeekTrialTests.approve
    answer = flash.DeepSeekTrialTests.answer
    fake_langextract = flash.DeepSeekTrialTests.fake_langextract
    extraction = flash.DeepSeekTrialTests.extraction

    def test_actual_v3_transport_import_reopen_all_statuses(self):
        for number, expected in enumerate(('complete', 'zero_candidates', 'partial', 'failed')):
            item = self.fixture(alias='case' + str(number))
            self.approve([item])
            extractions = [] if expected == 'zero_candidates' else [self.extraction('论述清晰。', direction='positive')]
            if expected == 'partial':
                extractions.append(self.extraction('不存在的引文'))
            answer = self.answer(json.dumps(dict(extractions=extractions), ensure_ascii=False))
            if expected == 'failed':
                answer = self.answer('not-json')
            transport, key = Mock(return_value=answer), Mock(return_value='synthetic-test-key')
            run_id = 'approved-' + expected
            with self.fake_langextract():
                summary = approved.execute(item['workspace'], self.plan, self.approval, item['alias'], item['section_id'],
                                           run_id, transport=transport, key_getter=key)
            self.assertEqual(summary['status'], expected)
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(key.call_count, 1)
            with closing(Workspace(item['workspace'])) as ws:
                state = ws.recover()
            self.assertEqual(state['extraction_runs'][-1]['status'], expected)
            candidates = [c for c in state['candidates'] if c.get('run_id') == run_id]
            self.assertTrue(all(c['status'] == 'pending_review' for c in candidates))
            self.assertTrue((Path(item['workspace']) / 'model-artifacts' / run_id / 'response-001.json').is_file())
            # The next case's approval must own a distinct ledger.
            (self.root / trial.LEDGER_FILENAME).unlink()

    def test_binding_and_budget_gates_precede_secret_and_transport(self):
        item = self.fixture()
        self.approve([item])
        key, transport = Mock(), Mock()
        for workspace, section in ((self.root, item['section_id']), (item['workspace'], 'private')):
            with self.assertRaises(ReviewError):
                approved.execute(workspace, self.plan, self.approval, 'one', section, 'refused', transport=transport, key_getter=key)
        checked = trial.validate_plan(self.plan, self.approval, 'one')
        ledger = trial.Ledger(checked[6], checked[4], checked[5], checked[0]['max_calls'])
        ledger.reserve('one', 'pending', 1, 8192)
        with self.fake_langextract(), self.assertRaisesRegex(ReviewError, 'E_USAGE_UNKNOWN_STOP'):
            approved.execute(item['workspace'], self.plan, self.approval, 'one', item['section_id'], 'blocked', transport=transport, key_getter=key)
        key.assert_not_called()
        transport.assert_not_called()

    def test_budget_preflight_and_missing_approval_no_secret(self):
        item = self.fixture()
        self.approve([item], budget_cny=0.000001)
        key, transport = Mock(), Mock()
        with self.fake_langextract(), self.assertRaisesRegex(ReviewError, 'E_BUDGET_EXHAUSTED'):
            approved.execute(item['workspace'], self.plan, self.approval, 'one', item['section_id'], 'no-budget', transport=transport, key_getter=key)
        self.approval.unlink()
        with self.assertRaises(OSError):
            approved.execute(item['workspace'], self.plan, self.approval, 'one', item['section_id'], 'no-approval', transport=transport, key_getter=key)
        key.assert_not_called()
        transport.assert_not_called()

    def test_launch_checkonly_and_desktop_parallel_path_require_no_qwen(self):
        item = self.fixture()
        self.approve([item])
        process = Mock(return_value=SimpleNamespace(returncode=0))
        result = approved.launch(item['workspace'], self.plan, self.approval, 'one', item['section_id'], 'check-only', check_only=True, process=process)
        self.assertEqual(result['status'], 'checked')
        self.assertIn('-CheckOnly', process.call_args.args[0])
        controller = Controller()
        controller.path = Path(item['workspace'])
        with patch.object(controller, '_check_model', side_effect=AssertionError('must not own Qwen')), \
             patch.object(approved, 'launch', return_value=dict(status='zero_candidates', accepted=0, rejected=0)) as launch:
            self.assertEqual(controller.extract_approved(self.plan, self.approval, 'one', item['section_id'])['extraction']['status'], 'zero_candidates')
        launch.assert_called_once()

    def test_injected_product_process_imports_failed_audit_despite_nonzero_exit(self):
        item = self.fixture()
        self.approve([item])
        def child(arguments):
            self.assertIn('-Workspace', arguments)
            with self.fake_langextract():
                summary = approved.execute(item['workspace'], self.plan, self.approval, 'one', item['section_id'], 'failed-child',
                    transport=Mock(return_value=self.answer('bad-json')), key_getter=Mock(return_value='synthetic-key'))
            self.assertEqual(summary['status'], 'failed')
            return SimpleNamespace(returncode=2)
        summary = approved.launch(item['workspace'], self.plan, self.approval, 'one', item['section_id'], 'failed-child', process=child)
        self.assertEqual(summary, dict(status='failed', accepted=0, rejected=0))
        with self.assertRaisesRegex(ReviewError, 'E_RUN_EXISTS'):
            approved.launch(item['workspace'], self.plan, self.approval, 'one', item['section_id'], 'failed-child', process=Mock())
