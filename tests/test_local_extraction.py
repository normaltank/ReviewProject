"""Synthetic transport/grounding regressions, not model accuracy tests."""
import importlib.util
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

from reviewproto.core import digest
from reviewproto.store import Workspace
from test_core_pipeline import native_variant


PATH = Path(__file__).resolve().parents[1] / "experiments" / "extract_local.py"
SPEC = importlib.util.spec_from_file_location("extract_local", PATH)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class LocalExtractionTests(unittest.TestCase):
    def workspace(self, root, text='合成测试原文'):
        source = root / 'input.json'
        source.write_text(json.dumps({'scores': [], 'sections': [{'section_id': 'one', 'label': '评审意见', 'text': text}]}, ensure_ascii=False), encoding='utf-8')
        directory = root / 'workspace'
        store = Workspace(directory)
        try:
            store.run(source, 'synthetic', 'json')
        finally:
            store.close()
        return directory

    @contextmanager
    def fake_provider(self, workspace, extract_response, run_id='synthetic-run'):
        lx, core = ModuleType('langextract'), ModuleType('langextract.core')
        core.base_model = Obj(BaseLanguageModel=object)
        core.tokenizer = Obj(UnicodeTokenizer=lambda: None)
        core.types = Obj()
        lx.extract = Mock(side_effect=extract_response)
        with patch.dict(sys.modules, {'langextract': lx, 'langextract.core': core}), \
             patch.object(adapter, 'examples', return_value=[]), \
             patch.object(adapter, 'version', return_value='synthetic'), \
             patch.object(sys, 'argv', ['adapter', '--workspace', str(workspace), '--run-id', run_id]), \
             patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')), \
             patch('builtins.print'):
            yield lx.extract

    def artifact(self, workspace, run_id='synthetic-run'):
        return json.loads((workspace / 'model-artifacts' / run_id / 'candidates.json').read_text(encoding='utf-8'))

    def test_endpoint_only_literal_loopback(self):
        self.assertEqual(adapter.local_endpoint("http://127.0.0.1:8766/v1/"),
                         "http://127.0.0.1:8766/v1/chat/completions")
        for endpoint in ("https://external.invalid/v1", "http://localhost:8766/v1",
                         "http://127.0.0.1.external.invalid/v1", "http://127.0.0.1/v1?key=x",
                         "http://user:pass@127.0.0.1/v1", "http://127.0.0.1/v2"):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, "E_LOCAL_ENDPOINT_REQUIRED"):
                adapter.local_endpoint(endpoint)

    def test_windows_do_not_repeat_final_paragraph(self):
        section = {"text": "甲乙丙丁", "paragraphs": [{"start": n, "end": n + 1} for n in range(4)]}
        self.assertEqual(list(adapter.windows(section, 6)), [(0, "甲乙丙丁", "paragraph_window")])
        windows = list(adapter.windows(section, 3))
        self.assertEqual([offset for offset, _, _ in windows], [0, 3])

    def test_oversize_is_explicit_and_not_truncated(self):
        self.assertEqual(list(adapter.windows({"text": "完整段落不可截断"}, 3)),
                         [(0, "完整段落不可截断", "oversize_paragraph")])

    def test_literal_unique_unicode_offset(self):
        section = {"source_id": "s", "section_id": "one"}
        evidence, fallback = adapter.literal_evidence(Obj(extraction_text="😀乙", char_interval=None), section, "甲😀乙", 10)
        self.assertEqual((evidence["start"], evidence["end"], evidence["quote"]), (11, 13, "😀乙"))
        self.assertTrue(fallback)

    def test_no_fuzzy_quote_or_ambiguous_match(self):
        section = {"source_id": "s", "section_id": "one"}
        for quote, text, error in (("重复", "重复再重复", "E_QUOTE_AMBIGUOUS"),
                                   ('"观点"', '“观点”', "E_QUOTE_NOT_FOUND"),
                                   ("", "原文", "E_QUOTE_NOT_FOUND")):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                adapter.literal_evidence(Obj(extraction_text=quote, char_interval=None), section, text, 0)

    def test_disagrees_with_aligner_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "E_ALIGNMENT_LITERAL_MISMATCH"):
            adapter.literal_evidence(Obj(extraction_text="乙", char_interval=Obj(start_pos=0, end_pos=1)),
                                     {"source_id": "s", "section_id": "one"}, "甲乙", 0)

    def test_convert_preserves_two_branches_and_marks_repeated_reason(self):
        text = "若可补资料则补资料，否则注明局限。"
        document = Obj(extractions=[
            Obj(extraction_class="opinion", extraction_text=text, char_interval=None, attributes={
                "object": "证据", "attribute_labels": ["证据责任"], "direction": "neutral",
                "speech_function": "suggestion", "requirement_strength": "recommended", "severity": "unknown",
                "action": "注明局限", "reason_quotes": [text], "condition_quotes": ["若可补资料"],
                "branch_conditions": ["若可补资料", "否则"], "branch_actions": ["则补资料", "注明局限"], "negation_quotes": []}),
        ])
        candidates, concepts, errors = adapter.convert(document, {"source_id": "s", "section_id": "one"}, text, 0, "w0-")
        self.assertEqual(errors, [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["alternatives"][0]["branches"]), 2)
        self.assertEqual(candidates[0]["conditions"][0]["meaning"], "unknown")
        self.assertEqual(candidates[0]["action"], "unknown")
        self.assertEqual(candidates[0]["requirement_strength"], "unknown")
        self.assertIn("branch_strength_requires_review", candidates[0]["review_flags"])
        self.assertEqual(document.extractions[0].attributes['action'], '注明局限')
        self.assertEqual(document.extractions[0].attributes['requirement_strength'], 'recommended')
        self.assertIn("reason_repeats_claim_requires_review", candidates[0]["review_flags"])
        self.assertEqual(len(candidates[0]["review_flags"]), len(set(candidates[0]["review_flags"])))
        self.assertEqual(concepts, [])
        self.assertEqual(candidates[0]["external_id"], "w0-0")

    def test_schema_has_one_class_and_only_literal_list_attributes(self):
        item = adapter.schema()['properties']['extractions']['items']
        self.assertEqual(set(item['properties']), {'opinion', 'opinion_attributes'})
        attrs = item['properties']['opinion_attributes']['properties']
        self.assertNotIn('opinion_id', attrs)
        self.assertNotIn('concept_definition', attrs)
        self.assertEqual(set(adapter.ATTRIBUTES), {'opinion'})
        for key in adapter.LIST_ATTRIBUTES:
            self.assertEqual(attrs[key], {'type': 'array', 'items': {'type': 'string'}})

    def test_attributes_require_exact_quotes_and_reject_suggestion_as_negation(self):
        text = '建议修改章节。'
        attrs = {'object': '章节', 'attribute_labels': ['章节安排'], 'direction': 'neutral',
                 'speech_function': 'suggestion', 'action': '修改章节', 'negation_quotes': ['建议'],
                 'reason_quotes': ['修改章节！']}
        result, _, errors = adapter.convert(Obj(extractions=[Obj(extraction_class='opinion', extraction_text=text,
                    attributes=attrs, char_interval=None)]), {'source_id': 's', 'section_id': 'one'}, text, 4, 'window-')
        self.assertEqual(result[0]['negation'], 'unknown')
        self.assertEqual(result[0]['reasons'], [])
        self.assertEqual(result[0]['action'], '修改章节')
        self.assertIn('E_QUOTE_NOT_FOUND', errors)
        self.assertIn('E_MODEL_NEGATION_NOT_NEGATIVE', errors)
        self.assertIn('invalid_negation_requires_review', result[0]['review_flags'])
        self.assertEqual(result[0]['evidence'][0]['start'], 4)

    def test_incomplete_alternatives_are_visible_without_inventing_missing_branch(self):
        text = '若有资料补案例，否则说明局限。'
        attrs = {'branch_conditions': ['若有资料', '否则'], 'branch_actions': ['补案例'], 'action': '补案例'}
        result, _, errors = adapter.convert(Obj(extractions=[Obj(extraction_class='opinion', extraction_text=text,
                    attributes=attrs, char_interval=None)]), {'source_id': 's', 'section_id': 'one'}, text, 0, 'window-')
        self.assertEqual(result[0]['alternatives'], [])
        self.assertTrue(all(c['meaning'] == 'unknown' for c in result[0]['conditions']))
        self.assertIn('E_MODEL_BRANCH_PAIRING', errors)
        self.assertIn('incomplete_alternative_requires_review', result[0]['review_flags'])

    def test_nested_quote_uses_opinion_context_without_global_first_match_guess(self):
        text = '不必新增实验。不必补资料。'
        attrs = {'action': '不必补资料', 'negation_quotes': ['不必']}
        result, _, errors = adapter.convert(Obj(extractions=[Obj(extraction_class='opinion', extraction_text='不必补资料。',
                    attributes=attrs, char_interval=None)]), {'source_id': 's', 'section_id': 'one'}, text, 10, 'window-')
        self.assertEqual(errors, [])
        self.assertEqual(result[0]['negation'], '不必')
        cited = next(e for e in result[0]['evidence'] if e['quote'] == '不必')
        self.assertEqual(cited['start'], 17)

    def test_run_hash_is_frozen_before_extraction_even_if_adapter_file_changes(self):
        # The fake extraction changes what is on disk while the run is in
        # flight. No model, socket, or optional package is used by this test.
        phase = {'value': b'adapter-at-start'}
        def extract(**kwargs):
            phase['value'] = b'adapter-replaced-during-run'
            return Obj(extractions=[])
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            with self.fake_provider(workspace, extract, 'startup-hash'), \
                 patch.object(Path, 'read_bytes', side_effect=lambda: phase['value']), \
                 patch('builtins.print'):
                self.assertEqual(adapter.main(), 0)
            payload = self.artifact(workspace, 'startup-hash')
            self.assertEqual(payload['config']['adapter_sha256'], adapter.digest(b'adapter-at-start'))
            self.assertNotEqual(payload['config']['adapter_sha256'], adapter.digest(phase['value']))

    def test_frozen_source_change_is_rejected_before_model_or_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            (workspace / 'source.json').write_text('{}', encoding='utf-8')
            with self.fake_provider(workspace, lambda **kwargs: Obj(extractions=[])) as model:
                with self.assertRaisesRegex(ValueError, '^E_SOURCE_CHANGED$'):
                    adapter.main()
                model.assert_not_called()
            self.assertFalse((workspace / 'model-artifacts').exists())

    def test_changed_source_cli_reports_only_safe_error_code(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            (workspace / 'source.json').write_text('{}', encoding='utf-8')
            result = subprocess.run([sys.executable, str(PATH), '--workspace', str(workspace)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr.strip(), 'E_SOURCE_CHANGED')
            self.assertEqual(result.stdout, '')
            self.assertFalse((workspace / 'model-artifacts').exists())

    def test_unsafe_cached_source_is_rechecked_before_model_or_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            # Simulate a pre-policy cache whose source hash matches an unsafe
            # original. Current shared source validation must still reject it.
            data = native_variant('oMath', 'comment')
            store = Workspace(workspace)
            try:
                state = store.state()
                state['source'].update(kind='native_docx', storage_file='source.docx', source_id=digest(data), sha256=digest(data))
                (workspace / 'source.docx').write_bytes(data)
                store.save(state)
            finally:
                store.close()
            with self.fake_provider(workspace, lambda **kwargs: Obj(extractions=[])) as model:
                with self.assertRaisesRegex(ValueError, '^E_UNSUPPORTED_FEATURE$'):
                    adapter.main()
                model.assert_not_called()
            self.assertFalse((workspace / 'model-artifacts').exists())

    def test_missing_or_empty_directory_is_not_initialized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for workspace in (root / 'missing', root / 'empty'):
                if workspace.name == 'empty':
                    workspace.mkdir()
                with self.fake_provider(workspace, lambda **kwargs: Obj(extractions=[])) as model:
                    with self.assertRaisesRegex(ValueError, '^E_WORKSPACE_EMPTY$'):
                        adapter.main()
                    model.assert_not_called()
                self.assertFalse((workspace / 'review.sqlite3').exists())
                self.assertFalse((workspace / 'model-artifacts').exists())
                self.assertFalse((workspace / '.gitignore').exists())
            self.assertFalse((root / 'missing').exists())

    def test_legitimate_empty_response_imports_as_zero_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            with self.fake_provider(workspace, lambda **kwargs: Obj(extractions=[])) as model:
                self.assertEqual(adapter.main(), 0)
                model.assert_called_once()
            payload = self.artifact(workspace)
            self.assertEqual((payload['status'], payload['candidates'], payload['errors']), ('complete', [], []))
            store = Workspace(workspace)
            try:
                result = store.import_extractions(payload)
                self.assertEqual(result['extraction_runs'][-1]['status'], 'zero_candidates')
            finally:
                store.close()

    def test_failed_empty_response_stays_failed_with_error(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            def failure(**kwargs):
                raise ValueError('E_MODEL_TRUNCATED')
            with self.fake_provider(workspace, failure):
                self.assertEqual(adapter.main(), 2)
            payload = self.artifact(workspace)
            self.assertEqual((payload['status'], payload['candidates'], payload['errors']), ('failed', [], ['E_MODEL_TRUNCATED']))
            store = Workspace(workspace)
            try:
                self.assertEqual(store.import_extractions(payload)['extraction_runs'][-1]['status'], 'failed')
            finally:
                store.close()

    def test_partial_response_preserves_error_and_valid_opinion(self):
        text = '建议修改标题。'
        def response(**kwargs):
            return Obj(extractions=[Obj(extraction_class='opinion', extraction_text=quote, char_interval=None, attributes={})
                                    for quote in [text, '合成不存在引文']])
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.fake_provider(workspace, response):
                self.assertEqual(adapter.main(), 0)
            payload = self.artifact(workspace)
            self.assertEqual(payload['status'], 'complete')
            self.assertEqual(payload['errors'], ['E_QUOTE_NOT_FOUND'])
            self.assertEqual(len(payload['candidates']), 1)
            store = Workspace(workspace)
            try:
                result = store.import_extractions(payload)
                self.assertEqual(result['extraction_runs'][-1]['status'], 'partial')
                self.assertEqual(len(result['extraction_runs'][-1]['accepted_ids']), 1)
            finally:
                store.close()

    def test_same_sentence_independent_requirements_survive_main_deduplication(self):
        text = '章节顺序可保持，标题应修改。'
        def response(**kwargs):
            return Obj(extractions=[Obj(extraction_class='opinion', extraction_text=text, char_interval=None,
                       attributes={'object': '篇章', 'attribute_labels': ['章节安排'], 'direction': 'neutral',
                                   'action': action, 'requirement_strength': strength}) for action, strength in
                       [('顺序可保持', 'optional'), ('标题应修改', 'mandatory')]])
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.fake_provider(workspace, response):
                self.assertEqual(adapter.main(), 0)
            payload = self.artifact(workspace)
            self.assertEqual(payload['errors'], [])
            self.assertEqual([(c['action'], c['requirement_strength']) for c in payload['candidates']],
                             [('顺序可保持', 'optional'), ('标题应修改', 'mandatory')])

    def test_fully_identical_overlapping_opinions_are_deduplicated(self):
        text = '建议修改标题。'
        def response(**kwargs):
            return Obj(extractions=[Obj(extraction_class='opinion', extraction_text=text, char_interval=None,
                       attributes={'object': '标题', 'attribute_labels': ['表达'], 'direction': 'neutral', 'action': '修改标题'})])
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.fake_provider(workspace, response) as model, \
                 patch.object(adapter, 'windows', return_value=iter([(0, text, 'paragraph_window'), (0, text, 'paragraph_window')])):
                self.assertEqual(adapter.main(), 0)
                self.assertEqual(model.call_count, 2)
            payload = self.artifact(workspace)
            self.assertEqual(len(payload['candidates']), 1)
            self.assertEqual(payload['errors'], [])


if __name__ == "__main__":
    unittest.main()
