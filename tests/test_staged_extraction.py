"""Synthetic staged CLI contracts; no model quality claims or real network."""
import importlib.util
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import ModuleType, SimpleNamespace as Obj
import unittest
from unittest.mock import patch

import test_local_extraction as local_tests
from reviewproto.store import Workspace

PATH = Path(__file__).resolve().parents[1] / 'experiments' / 'extract_staged.py'
SPEC = importlib.util.spec_from_file_location('extract_staged', PATH)
staged = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staged)


class StagedExtractionTests(unittest.TestCase):
    def workspace(self, root, text='论述清楚。', private=False, extra_sections=()):
        source = root / 'input.json'
        source.write_text(json.dumps({'scores': [{'label': '创新性与科学性（1-5分）', 'raw_value': '4'}],
            'metadata': {'reviewer': 'PRIVATE-IDENTITY'}, 'sections': [
                {'section_id': 'one', 'label': '作者不可见' if private else '评审意见', 'text': text,
                 'visibility': 'internal_only' if private else 'visibility_unknown'},
                {'section_id': 'secret', 'label': '作者不可见', 'text': 'PRIVATE-CONTENT', 'visibility': 'internal_only'},
                *extra_sections]},
            ensure_ascii=False), encoding='utf-8')
        workspace = root / 'workspace'
        store = Workspace(workspace)
        try:
            store.run(source, 'synthetic', 'json')
        finally:
            store.close()
        return workspace

    @contextmanager
    def run_mock(self, workspace, answers, extra=(), run_id='synthetic-run', before_request=None, on_request=None):
        """Exercise the real local provider against a fake HTTP boundary."""
        lx, core = ModuleType('langextract'), ModuleType('langextract.core')
        lx.data = Obj(Extraction=Obj, ExampleData=Obj)
        core.base_model = Obj(BaseLanguageModel=object)
        core.tokenizer = Obj(UnicodeTokenizer=lambda: None)
        core.types = Obj(ScoredOutput=Obj)
        requests, extracts = [], []
        def extract(**kwargs):
            extracts.append(kwargs)
            if before_request:
                before_request(len(extracts))
            prompt = json.dumps({'source': kwargs['text_or_documents'], 'examples': kwargs['examples']}, ensure_ascii=False, default=vars)
            answer = list(kwargs['model'].infer([prompt]))[0][0].output
            rows = json.loads(answer)['extractions']
            extractions = []
            for row in rows:
                cls = 'span' if 'span' in row else 'opinion'
                extractions.append(Obj(extraction_class=cls, extraction_text=row[cls],
                    attributes=row[cls + '_attributes'], char_interval=None))
            return Obj(extractions=extractions)
        lx.extract = extract
        def open_request(opener, request, timeout):
            requests.append(json.loads(request.data))
            if on_request:
                on_request(len(requests), request, opener)
            answer = answers[len(requests) - 1]
            if isinstance(answer, Exception):
                raise answer
            if isinstance(answer, tuple):
                rows, finish = answer
            else:
                rows, finish = answer, 'stop'
            wire = json.dumps({'choices': [{'finish_reason': finish, 'message': {'content': json.dumps({'extractions': rows}, ensure_ascii=False)}}],
                               'usage': {'prompt_tokens': 12, 'completion_tokens': 8}}).encode()
            response = Obj(read=lambda size: wire)
            class Reply:
                def __enter__(self):
                    return response
                def __exit__(self, *args):
                    return False
            return Reply()
        with patch.dict(sys.modules, {'langextract': lx, 'langextract.core': core}), \
             patch.object(staged, 'version', return_value='synthetic'), \
             patch.object(sys, 'argv', ['staged', '--workspace', str(workspace), '--section', 'one', '--run-id', run_id, *extra]), \
             patch('urllib.request.OpenerDirector.open', new=open_request), patch('builtins.print'):
            yield requests, extracts

    def artifact(self, workspace, name='candidates.json', run_id='synthetic-run'):
        return json.loads((workspace / 'model-artifacts' / run_id / name).read_text(encoding='utf-8'))

    def test_cue_without_model_recall_or_opinion_is_sidecar_only(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = local_tests.LocalExtractionTests().workspace(Path(directory), '图或表的标题需讨论。')
            calls = []
            def extract(**kwargs):
                calls.append(kwargs)
                return Obj(extractions=[])
            with local_tests.LocalExtractionTests().fake_provider(workspace, extract), \
                 patch.object(sys, 'argv', ['staged', '--workspace', str(workspace), '--section', 'one', '--run-id', 'synthetic-run']), \
                 patch.object(staged, 'version', return_value='synthetic'):
                self.assertEqual(staged.main(), 0)
            folder = workspace / 'model-artifacts' / 'synthetic-run'
            self.assertEqual(json.loads((folder / 'candidates.json').read_text(encoding='utf-8'))['candidates'], [])
            queue = json.loads((folder / 'queue.json').read_text(encoding='utf-8'))
            self.assertEqual(queue[0]['source'], 'cue_queue')
            self.assertEqual(queue[0]['semantics'], 'semantics_unknown')
            self.assertEqual(len(calls), 2)

    def test_two_stage_inputs_are_separate_and_only_review_results_are_imported(self):
        text = '😀论述清楚。建议重排章节。'
        recall = [{'span': '建议重排章节。', 'span_attributes': {'kind': 'modification'}}]
        review = [{'opinion': q, 'opinion_attributes': {}} for q in ['论述清楚。', '建议重排章节。']]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [recall, review]) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual([r['max_tokens'] for r in requests], [2048, 4096])
            self.assertEqual(extracts[1]['text_or_documents'], text)
            transmitted = json.dumps(requests, ensure_ascii=False)
            self.assertNotIn('PRIVATE-IDENTITY', transmitted)
            self.assertNotIn('PRIVATE-CONTENT', transmitted)
            self.assertNotIn('raw_value', transmitted)
            self.assertNotIn('span_attributes', requests[1]['messages'][1]['content'])
            self.assertEqual(set(requests[0]['response_format']['json_schema']['schema']['properties']['extractions']['items']['properties']), {'span', 'span_attributes'})
            payload = self.artifact(workspace)
            self.assertEqual([c['evidence'][0]['start'] for c in payload['candidates']], [1, 6])
            self.assertEqual(len(payload['candidates']), 2)
            store = Workspace(workspace)
            try:
                imported = store.import_extractions(payload)
                self.assertEqual(imported['extraction_runs'][-1]['status'], 'complete')
                for candidate in imported['candidates']:
                    self.assertEqual(candidate['status'], 'pending_review')
            finally:
                store.close()

    def test_network_attempt_is_durable_before_transport_and_full_prompt_is_fingerprinted(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            observed = []
            def on_request(number, request, opener):
                call = self.artifact(workspace, f'response-{number:03}.json')
                observed.append(call)
                self.assertEqual(call['status'], 'attempted')
                self.assertEqual(call['stage'], 'stage1')
                self.assertEqual(call['prompt_sha256'], staged.local.digest(call['prompt']))
                self.assertEqual(call['call_id'], number)
                self.assertEqual(request.full_url, 'http://127.0.0.1:8766/v1/chat/completions')
            with self.run_mock(workspace, [[]], on_request=on_request):
                self.assertEqual(staged.main(), 0)
            self.assertEqual(len(observed), 1)

    def test_budget_preserves_recall_and_cue_origins_as_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), '如果有图请补图。\n论述清楚。')
            recall = [{'span': '论述清楚。', 'span_attributes': {'kind': 'evaluation'}}]
            with self.run_mock(workspace, [recall], ['--max-refinements', '0']) as (requests, _):
                self.assertEqual(staged.main(), 0)
                self.assertEqual(len(requests), 1)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual({q['source'] for q in queue}, {'stage1_recall', 'cue_queue'})
            self.assertTrue(all(q['status'] == 'pending' for q in queue))
            self.assertTrue(all(q['semantics'] == 'semantics_unknown' for q in queue))
            self.assertTrue(all(q['span']['quote'] for q in queue))
            coverage = self.artifact(workspace, 'coverage.json')
            self.assertEqual(coverage['status'], 'partial')
            self.assertEqual(coverage['queue_unprocessed'], 2)
            store = Workspace(workspace)
            try:
                self.assertEqual(store.import_extractions(self.artifact(workspace))['extraction_runs'][-1]['status'], 'partial')
            finally:
                store.close()

    def test_source_is_revalidated_before_each_request_and_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), '论述清楚。')
            store = Workspace(workspace)
            try:
                original = store.state()
                candidate = original['candidates'][0]
                patch_payload = {'schema_version': 1, 'source_id': original['source']['source_id'], 'base_revision': original['revision'],
                    'actor': 'synthetic-editor', 'reason': 'synthetic-confirmation', 'edits': [
                    {'candidate_id': candidate['candidate_id'], 'fields': {'status': 'confirmed'}}]}
                store.apply(patch_payload)
                confirmed = store.state()
            finally:
                store.close()
            def before_request(number):
                if number == 2:
                    (workspace / 'source.json').write_text('{}', encoding='utf-8')
            recall = [{'span': '论述清楚。', 'span_attributes': {'kind': 'evaluation'}}]
            with self.run_mock(workspace, [recall], before_request=before_request) as (requests, _):
                self.assertEqual(staged.main(), 0)
                self.assertEqual(len(requests), 1)
            payload = self.artifact(workspace)
            self.assertIn('E_SOURCE_CHANGED', payload['errors'])
            self.assertEqual(self.artifact(workspace, 'queue.json')[0]['status'], 'failed')
            # Restore only this synthetic frozen file to inspect the real history.
            (workspace / 'source.json').write_bytes((Path(directory) / 'input.json').read_bytes())
            store = Workspace(workspace)
            try:
                self.assertEqual(store.state(), confirmed)
            finally:
                store.close()

    def test_private_section_and_invalid_endpoint_fail_before_artifacts_or_calls(self):
        for private, extra, error in [(True, [], 'E_PRIVATE_SECTION'),
                                     (False, ['--endpoint', 'http://localhost:8766/v1'], 'E_LOCAL_ENDPOINT_REQUIRED')]:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                workspace = self.workspace(Path(directory), private=private)
                with self.run_mock(workspace, [], extra) as (requests, _):
                    with self.assertRaisesRegex(ValueError, '^' + error + '$'):
                        staged.main()
                    self.assertEqual(requests, [])
                self.assertFalse((workspace / 'model-artifacts').exists())

    def test_empty_success_and_failed_empty_have_distinct_import_statuses(self):
        for answer, expected, exit_code in [([], 'zero_candidates', 0),
            (RuntimeError('synthetic-private-detail'), 'failed', 2), (([], 'length'), 'failed', 2)]:
            with self.subTest(expected=expected, answer=answer), tempfile.TemporaryDirectory() as directory:
                workspace = self.workspace(Path(directory))
                with self.run_mock(workspace, [answer]) as (requests, _):
                    self.assertEqual(staged.main(), exit_code)
                    self.assertEqual(len(requests), 1)
                payload = self.artifact(workspace)
                self.assertEqual(payload['candidates'], [])
                store = Workspace(workspace)
                try:
                    self.assertEqual(store.import_extractions(payload)['extraction_runs'][-1]['status'], expected)
                finally:
                    store.close()

    def test_truncated_review_never_becomes_candidate_and_recall_is_retained(self):
        recall = [{'span': '建议补图。', 'span_attributes': {'kind': 'modification'}}]
        review = [{'opinion': '建议补图。', 'opinion_attributes': {}}]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), '建议补图。')
            with self.run_mock(workspace, [recall, (review, 'length')]):
                self.assertEqual(staged.main(), 0)
            self.assertEqual(self.artifact(workspace)['candidates'], [])
            self.assertIn('E_MODEL_TRUNCATED', self.artifact(workspace)['errors'])
            self.assertEqual(len(self.artifact(workspace, 'recall.json')['spans']), 1)
            self.assertEqual(self.artifact(workspace, 'queue.json')[0]['status'], 'failed')
            self.assertEqual(self.artifact(workspace, 'coverage.json')['status'], 'partial')

    def test_strict_recall_quotes_reject_modified_or_repeated_text(self):
        answers = [[{'span': quote, 'span_attributes': {'kind': 'evaluation'}} for quote in ['论述清楚。', '论述清楚！']]]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), '论述清楚。论述清楚。')
            with self.run_mock(workspace, answers):
                self.assertEqual(staged.main(), 0)
            self.assertEqual(self.artifact(workspace, 'recall.json')['spans'], [])
            self.assertEqual(set(self.artifact(workspace)['errors']), {'E_QUOTE_AMBIGUOUS', 'E_QUOTE_NOT_FOUND'})

    def test_cue_prioritizes_complete_adjacent_paragraphs_and_deduplicates_context_only(self):
        text = '论述清楚。\n若有记录可补图。\n否则说明局限。'
        recall = [{'span': q, 'span_attributes': {'kind': 'unknown'}} for q in ['若有记录可补图。', '否则说明局限。']]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [recall, [], []], ['--max-refinements', '1']) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual(extracts[1]['text_or_documents'], text)
            self.assertEqual(len(requests), 2)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 4)
            self.assertEqual([q['source'] for q in queue[:2]], ['cue_queue', 'cue_queue'])
            self.assertEqual(queue[0]['status'], 'processed')
            self.assertEqual(queue[2]['status'], 'processed')
            self.assertTrue(all(q['status'] == 'processed' and q['context']['quote'] == text for q in queue))

    def test_overlapping_cues_review_one_complete_three_paragraph_context(self):
        text = '若能取得完整记录，\n可补一张对照表。\n否则说明资料覆盖范围。'
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [[], [], []]) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual([e['text_or_documents'] for e in extracts[1:]], [text])
            self.assertEqual(len(requests), 2)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 2)
            self.assertEqual([q['span']['quote'] for q in queue], ['若', '否则'])
            self.assertTrue(all(q['context']['quote'] == text and q['status'] == 'processed' for q in queue))
            self.assertEqual(self.artifact(workspace)['errors'], [])

    def test_oversize_cue_closure_blocks_fragmented_recall_bypass(self):
        first, middle, last = '若' + '甲' * 210 + '，', '乙' * 210 + '。', '否则' + '丙' * 210 + '。'
        text = '\n'.join([first, middle, last])
        recall = [{'span': middle, 'span_attributes': {'kind': 'unknown'}}]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [recall, []]) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual(len(requests), 2)
            self.assertTrue(all('span' in e['examples'][0].extractions[0].extraction_class for e in extracts))
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 3)
            self.assertEqual({q['source'] for q in queue}, {'cue_queue', 'stage1_recall'})
            self.assertTrue(all(q['context']['quote'] == text and q['status'] == 'boundary_pending' for q in queue))
            self.assertTrue(all(q['stage2_calls'] == [] and q['semantics'] == 'semantics_unknown' for q in queue))
            self.assertEqual(self.artifact(workspace, 'coverage.json')['status'], 'partial')
            self.assertEqual(self.artifact(workspace, 'coverage.json')['queue_unprocessed'], 3)
            store = Workspace(workspace)
            try:
                self.assertEqual(store.import_extractions(self.artifact(workspace))['extraction_runs'][-1]['status'], 'partial')
            finally:
                store.close()

    def test_cue_closure_never_merges_selected_sections_or_reads_private_section(self):
        first = '若能取得完整记录，\n可补一张对照表。\n否则说明资料覆盖范围。'
        second = '如果取得两次记录，\n可说明观测范围。\n否则补充资料局限。'
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), first, extra_sections=[
                {'section_id': 'two', 'label': '评审意见', 'text': second, 'visibility': 'visibility_unknown'}])
            with self.run_mock(workspace, [[], [], [], []], ['--section', 'two']) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual([e['text_or_documents'] for e in extracts], [first, second, first, second])
            self.assertEqual(len(requests), 4)
            self.assertNotIn('PRIVATE-CONTENT', json.dumps(requests))
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 4)
            for item in queue:
                expected = first if item['span']['section_id'] == 'one' else second
                self.assertEqual(item['context']['section_id'], item['span']['section_id'])
                self.assertEqual(item['context']['quote'], expected)

    def test_recall_only_paragraphs_remain_separate_without_cues(self):
        first, second = '论述清楚。', '建议补充图表。'
        text = first + '\n' + second
        recall = [{'span': q, 'span_attributes': {'kind': 'unknown'}} for q in (first, second)]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [recall, [], []]) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual([e['text_or_documents'] for e in extracts[1:]], [first, second])
            self.assertEqual(len(requests), 3)
            self.assertEqual(len(self.artifact(workspace, 'queue.json')), 2)

    def test_merged_cue_context_retains_codepoint_grounding_and_original_bytes(self):
        text = '😀若能取得完整记录，\n可补一张对照表。\n否则说明资料覆盖范围。'
        recall = [{'span': '可补一张对照表。', 'span_attributes': {'kind': 'modification'}}]
        review = [{'opinion': '可补一张对照表。', 'opinion_attributes': {}},
                  {'opinion': '否则说明资料覆盖范围。', 'opinion_attributes': {}}]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            source_bytes = (workspace / 'source.json').read_bytes()
            with self.run_mock(workspace, [recall, review]) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual(len(requests), 2)
            self.assertEqual(extracts[1]['text_or_documents'], text)
            self.assertEqual((workspace / 'source.json').read_bytes(), source_bytes)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 3)
            self.assertTrue(all(q['context']['quote'] == text and q['status'] == 'processed' for q in queue))
            candidates = self.artifact(workspace)['candidates']
            self.assertEqual([c['evidence'][0]['start'] for c in candidates], [11, 20])
            for candidate in candidates:
                evidence = candidate['evidence'][0]
                self.assertEqual(text[evidence['start']:evidence['end']], evidence['quote'])

    def test_merged_cue_and_recall_queue_survives_budget_without_fragment_requests(self):
        text = '若能取得完整记录，\n可补一张对照表。\n否则说明资料覆盖范围。'
        recall = [{'span': '可补一张对照表。', 'span_attributes': {'kind': 'modification'}}]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [recall], ['--max-refinements', '0']) as (requests, _):
                self.assertEqual(staged.main(), 0)
            self.assertEqual(len(requests), 1)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 3)
            self.assertTrue(all(q['context']['quote'] == text and q['status'] == 'pending' for q in queue))
            self.assertEqual(self.artifact(workspace, 'coverage.json')['queue_budget_unprocessed'], 3)
            self.assertEqual(self.artifact(workspace, 'coverage.json')['status'], 'partial')

    def test_cue_context_overlap_closure_is_transitive(self):
        text = '若有记录，\n可补图。\n因为观测少，\n须说明局限。\n否则保留待核。'
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [[], [], [], []]) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual([e['text_or_documents'] for e in extracts[1:]], [text])
            self.assertEqual(len(requests), 2)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 3)
            self.assertTrue(all(q['context']['quote'] == text for q in queue))

    def test_unrelated_recall_outside_cue_closure_keeps_its_own_context_and_budget(self):
        context = '若能补图，\n可补图。\n否则说明局限。\n分隔说明。'
        text = context + '\n论述清楚。'
        recall = [{'span': '论述清楚。', 'span_attributes': {'kind': 'evaluation'}}]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [recall, []], ['--max-refinements', '1']) as (requests, extracts):
                self.assertEqual(staged.main(), 0)
            self.assertEqual([e['text_or_documents'] for e in extracts[1:]], [context])
            self.assertEqual(len(requests), 2)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(len(queue), 3)
            remaining = next(q for q in queue if q['source'] == 'stage1_recall')
            self.assertEqual(remaining['context']['quote'], '论述清楚。')
            self.assertEqual(remaining['status'], 'pending')
            self.assertEqual(self.artifact(workspace, 'coverage.json')['queue_budget_unprocessed'], 1)

    def test_unfittable_complete_context_stays_explicitly_pending_without_truncation(self):
        text = '甲' * 305 + '。\n否则' + '乙' * 305 + '。'
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [[], []]) as (requests, _):
                self.assertEqual(staged.main(), 0)
                self.assertEqual(len(requests), 2)
            queue = self.artifact(workspace, 'queue.json')
            self.assertEqual(queue[0]['status'], 'boundary_pending')
            self.assertEqual(queue[0]['context']['quote'], text)
            self.assertIn('E_CONTEXT_BOUNDARY_REQUIRES_REVIEW', self.artifact(workspace)['errors'])

    def test_network_call_budget_keeps_queue_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), '若有图请补图。')
            with self.run_mock(workspace, [[]], ['--max-calls', '1']) as (requests, _):
                self.assertEqual(staged.main(), 0)
                self.assertEqual(len(requests), 1)
            self.assertEqual(self.artifact(workspace, 'coverage.json')['queue_budget_unprocessed'], 1)
            self.assertEqual(self.artifact(workspace)['config']['model_requests'], 1)
            self.assertEqual(self.artifact(workspace)['config']['external_model_requests'], 0)

    def test_only_fully_equal_model_candidates_are_deduplicated(self):
        text = '章节顺序可保持，标题应修改。'
        recall = [{'span': text, 'span_attributes': {'kind': 'unknown'}}]
        review = [{'opinion': text, 'opinion_attributes': {'action': action}} for action in ['顺序可保持', '标题应修改', '顺序可保持']]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.run_mock(workspace, [recall, review]):
                self.assertEqual(staged.main(), 0)
            self.assertEqual([c['action'] for c in self.artifact(workspace)['candidates']], ['顺序可保持', '标题应修改'])

    def test_existing_run_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            with self.run_mock(workspace, [[]]):
                self.assertEqual(staged.main(), 0)
            previous = (workspace / 'model-artifacts' / 'synthetic-run' / 'candidates.json').read_bytes()
            with self.run_mock(workspace, []) as (requests, _):
                with self.assertRaisesRegex(ValueError, '^E_ARTIFACT_EXISTS$'):
                    staged.main()
                self.assertEqual(requests, [])
            self.assertEqual((workspace / 'model-artifacts' / 'synthetic-run' / 'candidates.json').read_bytes(), previous)

    def test_proxy_and_redirect_handlers_explicitly_disable_environment_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            build_opener = staged.urllib.request.build_opener
            with self.run_mock(workspace, [[]]), patch.dict('os.environ', {'HTTP_PROXY': 'http://external.invalid:80'}), \
                 patch.object(staged.urllib.request, 'build_opener', wraps=build_opener) as builder:
                self.assertEqual(staged.main(), 0)
                self.assertEqual(builder.call_args.args[0].proxies, {})
                self.assertIsInstance(builder.call_args.args[1], staged.local.NoRedirect)
            self.assertIsNone(staged.local.NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'http://external.invalid'))

    def test_unsafe_old_cached_source_is_rejected_by_current_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            data = local_tests.native_variant('oMath', 'comment')
            store = Workspace(workspace)
            try:
                state = store.state()
                state['source'].update(kind='native_docx', storage_file='source.docx',
                    source_id=local_tests.digest(data), sha256=local_tests.digest(data))
                (workspace / 'source.docx').write_bytes(data)
                store.save(state)
            finally:
                store.close()
            with self.run_mock(workspace, []) as (requests, _):
                with self.assertRaisesRegex(ValueError, '^E_UNSUPPORTED_FEATURE$'):
                    staged.main()
                self.assertEqual(requests, [])
            self.assertFalse((workspace / 'model-artifacts').exists())

    def test_review_quote_rejection_and_sidecar_hashes_survive_import(self):
        text = '😀论述清楚。'
        recall = [{'span': '论述清楚。', 'span_attributes': {'kind': 'evaluation'}}]
        review = [{'opinion': q, 'opinion_attributes': {}} for q in ['论述清楚。', '论述清楚！']]
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            store = Workspace(workspace)
            try:
                from reviewproto.store import template
                patch_payload = template(store.state())
                patch_payload.update(actor='synthetic-editor', reason='synthetic-confirmation')
                patch_payload['edits'] = patch_payload['edits'][:1]
                patch_payload['edits'][0]['fields']['status'] = 'confirmed'
                store.apply(patch_payload)
                original = store.state()
            finally:
                store.close()
            with self.run_mock(workspace, [recall, review]):
                self.assertEqual(staged.main(), 0)
            payload = self.artifact(workspace)
            self.assertEqual(payload['errors'], ['E_QUOTE_NOT_FOUND'])
            self.assertEqual(len(payload['candidates']), 1)
            folder = workspace / 'model-artifacts' / 'synthetic-run'
            for name, fingerprint in payload['config']['sidecar_sha256'].items():
                self.assertEqual(staged.local.digest((folder / name).read_bytes()), fingerprint)
            store = Workspace(workspace)
            try:
                imported = store.import_extractions(payload)
                self.assertEqual(imported['extraction_runs'][-1]['status'], 'partial')
                for key in ['source', 'scores', 'sections', 'decisions']:
                    self.assertEqual(imported[key], original[key])
            finally:
                store.close()

    def test_cue_queue_retains_original_sentence_span_with_stable_id(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), '论述清楚。建议补图或者补表。')
            with self.run_mock(workspace, [[], []]):
                self.assertEqual(staged.main(), 0)
            first = self.artifact(workspace, 'queue.json')[0]
            self.assertEqual(first['sentence_span']['quote'], '建议补图或者补表。')
            self.assertEqual(first['span']['quote'], '或者')
            with self.run_mock(workspace, [[], []], run_id='synthetic-second'):
                self.assertEqual(staged.main(), 0)
            second = self.artifact(workspace, 'queue.json', 'synthetic-second')[0]
            self.assertEqual(first['id'], second['id'])

    def test_previously_ingested_run_id_is_refused_even_without_artifact_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            store = Workspace(workspace)
            try:
                state = store.state()
                store.import_extractions({'schema_version': 1, 'source_id': state['source']['source_id'],
                    'run_id': 'synthetic-run', 'extractor': 'synthetic', 'model': 'synthetic', 'config': {},
                    'sections': [{'section_id': 'one', 'text_sha256': staged.local.digest('论述清楚。')}],
                    'candidates': [], 'status': 'complete', 'errors': []})
            finally:
                store.close()
            with self.run_mock(workspace, []) as (requests, _):
                with self.assertRaisesRegex(ValueError, '^E_RUN_ID_EXISTS$'):
                    staged.main()
                self.assertEqual(requests, [])
            self.assertFalse((workspace / 'model-artifacts').exists())

    def test_unmanaged_workspace_cli_reports_only_safe_error_code(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / 'review.sqlite3').write_bytes(b'synthetic invalid database')
            result = subprocess.run([sys.executable, str(PATH), '--workspace', str(workspace),
                '--section', 'one', '--run-id', 'synthetic-run'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr.strip(), 'E_WORKSPACE_UNMANAGED')


if __name__ == '__main__':
    unittest.main()
