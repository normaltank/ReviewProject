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
    def fake_provider(self, workspace, extract_response, run_id='synthetic-run', extra_args=()):
        lx, core = ModuleType('langextract'), ModuleType('langextract.core')
        core.base_model = Obj(BaseLanguageModel=object)
        core.tokenizer = Obj(UnicodeTokenizer=lambda: None)
        core.types = Obj(ScoredOutput=Obj)
        lx.data = Obj(Extraction=Obj, ExampleData=Obj)
        lx.extract = Mock(side_effect=extract_response)
        with patch.dict(sys.modules, {'langextract': lx, 'langextract.core': core}), \
             patch.object(adapter, 'version', return_value='synthetic'), \
             patch.object(sys, 'argv', ['adapter', '--workspace', str(workspace), '--run-id', run_id, *extra_args]), \
             patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')), \
             patch('builtins.print'):
            yield lx.extract

    def artifact(self, workspace, run_id='synthetic-run'):
        return json.loads((workspace / 'model-artifacts' / run_id / 'candidates.json').read_text(encoding='utf-8'))

    def test_default_protocol_keeps_v3_public_interface_and_cli_configuration(self):
        self.assertEqual(adapter.PROMPT_VERSION, 'review-opinions-local-v3')
        self.assertNotIn('branch_relation', adapter.schema()['properties']['extractions']['items']['properties']['opinion_attributes']['properties'])
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            with self.fake_provider(workspace, lambda **kwargs: Obj(extractions=[])) as model:
                self.assertEqual(adapter.main(), 0)
            call = model.call_args.kwargs
            config = self.artifact(workspace)['config']
            self.assertEqual(config['protocol'], 'v3')
            self.assertEqual(config['prompt_version'], 'review-opinions-local-v3')
            self.assertEqual(call['prompt_description'], adapter.INSTRUCTION)
            self.assertEqual(len(call['examples'][0].extractions), 6)
            self.assertNotIn('branch_relation', call['examples'][0].extractions[3].attributes)
            self.assertEqual((config['temperature'], config['window_chars'], config['max_output_tokens']), (0, 600, 4096))

    def test_protocols_preserve_frozen_synthetic_instructions_schemas_and_examples(self):
        # Independent fingerprints from the pre-selection frozen v3/v4
        # protocols. These cover synthetic few-shot material, never real data.
        expected = {
            'v3': ('c5abdf8d9dc43c0e71a7fecab299de6b841386117d45d6b92e4cd556ea3eb6c2',
                   '86500400377333db277fbad422a3917c9abeab1a16a3441e0166e36a30346fb0',
                   'f960e33240481090adc3eb73a6016c5d5095fdad6b31f14931d0bc1e8bbf80ec'),
            'v4': ('386279a6e8c8ff3337aa19b5ff3a238bd916fa1f44149306575f35a497a070c8',
                   'ad343442c35d5715ed4da724cfd0b57b2931f3d5abd346de63333dbc0d72de77',
                   'ca189482a3e6651c3e8ebcae3824dfbf7d39f9eb8e6e59803c90b5ddd0d308ee'),
        }
        lx = Obj(data=Obj(Extraction=Obj, ExampleData=Obj))
        for protocol, hashes in expected.items():
            with self.subTest(protocol=protocol):
                selected = adapter.protocol_config(protocol)
                encoded_examples = json.dumps(adapter.examples(lx, protocol), ensure_ascii=False,
                                               sort_keys=True, default=vars)
                self.assertEqual((adapter.digest(selected['instruction']),
                                  adapter.digest(json.dumps(adapter.schema(protocol), sort_keys=True)),
                                  adapter.digest(encoded_examples)), hashes)

    def test_selected_schema_enum_mutation_does_not_change_other_protocols_or_defaults(self):
        original_enums = {key: list(values) for key, values in adapter.ENUMS.items()}
        original_schemas = {protocol: json.loads(json.dumps(adapter.schema(protocol))) for protocol in ('v3', 'v4')}
        selected = adapter.protocol_config('v4')['schema']
        attrs = selected['properties']['extractions']['items']['properties']['opinion_attributes']['properties']
        try:
            attrs['direction']['enum'].append('synthetic_mutation')
            attrs['branch_relation']['enum'].clear()
            self.assertEqual(adapter.ENUMS, original_enums)
            for protocol in ('v3', 'v4'):
                self.assertEqual(adapter.schema(protocol), original_schemas[protocol])
        finally:
            # A failing pre-fix run must not poison subsequent tests.
            for key, values in original_enums.items():
                adapter.ENUMS[key][:] = values

    def test_explicit_v4_selects_actual_prompt_schema_examples_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            requests = []
            def respond(**kwargs):
                # Exercise the adapter's real request assembly, using a
                # synthetic transport so no local model or socket is involved.
                list(kwargs['model'].infer(['synthetic formatted prompt']))
                return Obj(extractions=[])
            def transport(request, **kwargs):
                requests.append(json.loads(request.data))
                response = Mock()
                response.read.return_value = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}).encode()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                return response
            with self.fake_provider(workspace, respond, extra_args=('--protocol', 'v4')) as model, \
                 patch('urllib.request.OpenerDirector.open', side_effect=transport):
                self.assertEqual(adapter.main(), 0)
            call = model.call_args.kwargs
            config = self.artifact(workspace)['config']
            self.assertEqual(config['protocol'], 'v4')
            self.assertEqual(config['prompt_version'], 'review-opinions-local-v4')
            self.assertEqual(requests[0]['messages'][0]['content'], call['prompt_description'])
            self.assertEqual(config['prompt_sha256'], digest(call['prompt_description'].encode('utf-8')))
            sent_schema = requests[0]['response_format']['json_schema']['schema']
            self.assertIn('branch_relation', sent_schema['properties']['extractions']['items']['properties']['opinion_attributes']['properties'])
            self.assertEqual(config['schema_sha256'], digest(json.dumps(sent_schema, sort_keys=True).encode('utf-8')))
            self.assertEqual(len(call['examples'][0].extractions), 10)
            self.assertEqual(call['examples'][0].extractions[4].attributes['branch_relation'], 'either_or')
            self.assertEqual((requests[0]['temperature'], requests[0]['max_tokens']), (0, 4096))
            self.assertEqual(adapter.PROMPT_VERSION, 'review-opinions-local-v3')

    def test_invalid_protocol_refuses_before_model_workspace_or_artifact_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / 'missing'
            result = subprocess.run([sys.executable, str(PATH), '--workspace', str(workspace), '--protocol', 'invalid'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('invalid choice', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertFalse(workspace.exists())

    def convert_attrs(self, text, attrs, *, opinion=None, start=0):
        document = Obj(extractions=[Obj(extraction_class='opinion', extraction_text=opinion or text,
                                        attributes=attrs, char_interval=None)])
        result, _, errors = adapter.convert(document, {'source_id': 's', 'section_id': 'one'}, text, start, 'w-')
        return result[0], errors

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

    def test_either_or_preserves_actions_without_inventing_selection_conditions(self):
        text = '建议补一张图，或者补一张表。'
        attrs = {'branch_relation': 'either_or', 'branch_conditions': [],
                 'branch_actions': ['补一张图', '补一张表'], 'action': '补一张图',
                 'requirement_strength': 'recommended'}
        document = Obj(extractions=[Obj(extraction_class='opinion', extraction_text=text,
                                        attributes=attrs, char_interval=None)])
        result, _, errors = adapter.convert(document, {'source_id': 's', 'section_id': 'one'}, text, 0, 'w-')
        self.assertEqual(errors, [])
        self.assertEqual(result[0]['alternatives'], [{'relation': 'either_or', 'provenance': 'explicit',
                         'branches': [{'condition': 'unknown', 'action': '补一张图', 'evidence_indices': [1]},
                                      {'condition': 'unknown', 'action': '补一张表', 'evidence_indices': [2]}]}])
        self.assertEqual(result[0]['conditions'], [])
        self.assertEqual((result[0]['action'], result[0]['requirement_strength']), ('unknown', 'unknown'))
        self.assertIn('semantic_model_unverified', result[0]['review_flags'])
        self.assertIn('branch_strength_requires_review', result[0]['review_flags'])
        self.assertEqual(attrs['requirement_strength'], 'recommended')

    def test_either_or_round_trips_through_existing_candidate_contract_as_pending(self):
        text = '建议补图或补表。'
        def response(**kwargs):
            return Obj(extractions=[Obj(extraction_class='opinion', extraction_text=text, char_interval=None,
                       attributes={'branch_relation': 'either_or', 'branch_actions': ['补图', '补表']})])
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory), text)
            with self.fake_provider(workspace, response):
                self.assertEqual(adapter.main(), 0)
            store = Workspace(workspace)
            try:
                state = store.import_extractions(self.artifact(workspace))
                run = state['extraction_runs'][-1]
                self.assertEqual(run['status'], 'complete')
                saved = next(c for c in state['candidates'] if c['candidate_id'] in run['accepted_ids'])
                self.assertEqual(saved['alternatives'][0]['relation'], 'either_or')
                self.assertEqual([b['condition'] for b in saved['alternatives'][0]['branches']], ['unknown', 'unknown'])
                self.assertEqual(saved['status'], 'pending_review')
                self.assertIn('branch_relation_semantics_requires_review', saved['review_flags'])
            finally:
                store.close()

    def test_explicit_conditional_relation_preserves_literal_pairs_and_group_strength(self):
        candidate, errors = self.convert_attrs('若有数据可补图，否则须说明局限。', {
            'branch_relation': 'conditional_branches', 'branch_conditions': ['若有数据', '否则'],
            'branch_actions': ['可补图', '须说明局限'], 'requirement_strength': 'mandatory', 'action': '须说明局限'})
        self.assertEqual(errors, [])
        group = candidate['alternatives'][0]
        self.assertEqual(group['relation'], 'conditional_branches')
        self.assertEqual([(b['condition'], b['action']) for b in group['branches']],
                         [('若有数据', '可补图'), ('否则', '须说明局限')])
        self.assertEqual((candidate['action'], candidate['requirement_strength']), ('unknown', 'unknown'))

    def test_none_unknown_and_invalid_relation_never_upgrade_from_branch_lists(self):
        for relation in ('none', 'unknown', 'invented', ['either_or']):
            with self.subTest(relation=relation):
                candidate, errors = self.convert_attrs('建议补图或补表。', {
                    'branch_relation': relation, 'branch_actions': ['补图', '补表']})
                self.assertEqual(candidate['alternatives'], [])
                self.assertIn('E_MODEL_BRANCH_RELATION_CONFLICT', errors)

    def test_no_branch_lists_never_construct_groups_from_connectives_or_quoted_actions(self):
        for text in ('建议补图，并补表。', '图或表的标题不清楚。', '文中写‘补图或补表’，此表述不清楚。'):
            for relation in ('none', 'unknown', None):
                with self.subTest(text=text, relation=relation):
                    attrs = {} if relation is None else {'branch_relation': relation}
                    candidate, errors = self.convert_attrs(text, attrs)
                    self.assertEqual(candidate['alternatives'], [])
                    self.assertEqual(errors, [])

    def test_even_explicit_model_relation_on_nouns_or_quotation_remains_semantically_unverified(self):
        for text, actions in [('图或表的标题不清楚。', ['图', '表']),
                              ('文中写‘补图或补表’，此表述不清楚。', ['补图', '补表'])]:
            with self.subTest(text=text):
                candidate, errors = self.convert_attrs(text, {'branch_relation': 'either_or', 'branch_actions': actions})
                self.assertEqual(errors, [])  # Surface validity is not semantic acceptance.
                self.assertIn('semantic_model_unverified', candidate['review_flags'])
                self.assertIn('branch_relation_semantics_requires_review', candidate['review_flags'])

    def test_either_or_requires_two_literal_actions_and_an_intervening_connective(self):
        cases = [
            ('建议补图并补表。', ['补图', '补表'], 'E_MODEL_EITHER_OR_CONNECTIVE'),
            ('建议补图，或许补表。', ['补图', '补表'], 'E_MODEL_EITHER_OR_CONNECTIVE'),
            ('图或表需要修改。建议补图并补表。', ['补图', '补表'], 'E_MODEL_EITHER_OR_CONNECTIVE'),
            ('建议补图或补表。', ['补图'], 'E_MODEL_BRANCH_PAIRING'),
            ('建议补图或补表。', ['补图', '补图'], 'E_MODEL_BRANCH_PAIRING'),
            ('建议补图或补表。', ['补图', '补表！'], 'E_MODEL_BRANCH_OUTSIDE_OPINION'),
        ]
        for text, actions, error in cases:
            with self.subTest(text=text, actions=actions):
                candidate, errors = self.convert_attrs(text, {'branch_relation': 'either_or', 'branch_actions': actions,
                                                       'action': '补图', 'requirement_strength': 'mandatory'})
                self.assertEqual(candidate['alternatives'], [])
                self.assertIn(error, errors)
                self.assertEqual((candidate['action'], candidate['requirement_strength']), ('unknown', 'unknown'))

    def test_either_or_does_not_accept_invented_selection_conditions(self):
        for conditions in (['unknown', 'unknown'], ['建议', '或者']):
            with self.subTest(conditions=conditions):
                candidate, errors = self.convert_attrs('建议补图，或者补表。', {'branch_relation': 'either_or',
                    'branch_conditions': conditions, 'branch_actions': ['补图', '补表']})
                self.assertEqual(candidate['alternatives'], [])
                self.assertIn('E_MODEL_EITHER_OR_CONDITIONS', errors)

    def test_malformed_v4_branch_conditions_do_not_become_empty_valid_conditions(self):
        candidate, errors = self.convert_attrs('建议补图或补表。', {'branch_relation': 'either_or',
            'branch_conditions': 'unknown', 'branch_actions': ['补图', '补表']})
        self.assertEqual(candidate['alternatives'], [])
        self.assertIn('E_MODEL_QUOTE_LIST_BRANCH_CONDITIONS', errors)

    def test_either_or_unicode_offsets_and_repeated_action_ambiguity(self):
        text = '前言。建议补😀图，或者补表。'
        candidate, errors = self.convert_attrs(text, {'branch_relation': 'either_or', 'branch_actions': ['补😀图', '补表']},
                                                opinion='建议补😀图，或者补表。', start=8)
        self.assertEqual(errors, [])
        for branch in candidate['alternatives'][0]['branches']:
            evidence = candidate['evidence'][branch['evidence_indices'][0]]
            self.assertEqual(text[evidence['start'] - 8:evidence['end'] - 8], branch['action'])
        candidate, errors = self.convert_attrs('建议补图或补表；补图需说明。', {
            'branch_relation': 'either_or', 'branch_actions': ['补图', '补表']})
        self.assertEqual(candidate['alternatives'], [])
        self.assertIn('E_QUOTE_AMBIGUOUS', errors)

    def test_v4_conditional_requires_complete_pairs_inside_opinion(self):
        for conditions, actions, error in [([], [], 'E_MODEL_BRANCH_PAIRING'),
                (['若有数据', '否则'], ['补图'], 'E_MODEL_BRANCH_PAIRING'),
                (['若有数据', '否则'], ['补图', '说明局限！'], 'E_MODEL_BRANCH_OUTSIDE_OPINION')]:
            with self.subTest(conditions=conditions, actions=actions):
                candidate, errors = self.convert_attrs('若有数据补图，否则说明局限。', {
                    'branch_relation': 'conditional_branches', 'branch_conditions': conditions, 'branch_actions': actions})
                self.assertEqual(candidate['alternatives'], [])
                self.assertIn(error, errors)
        candidate, errors = self.convert_attrs('建议补图或补表。另须补摘要。', {
            'branch_relation': 'either_or', 'branch_actions': ['补图', '补摘要']}, opinion='建议补图或补表。')
        self.assertEqual(candidate['alternatives'], [])
        self.assertIn('E_MODEL_BRANCH_OUTSIDE_OPINION', errors)

    def test_missing_relation_uses_v3_pairing_without_guessing_either_or(self):
        candidate, errors = self.convert_attrs('建议补图或补表。', {'branch_actions': ['补图', '补表']})
        self.assertEqual(candidate['alternatives'], [])
        self.assertIn('E_MODEL_BRANCH_PAIRING', errors)

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
