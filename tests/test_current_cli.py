"""Current public command surface and durable attention analysis."""
import io
import json
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path

from reviewproto.attention import AttentionWorkspace
from reviewproto.cli import main


RETIRED = ('run', 'review', 'export-template', 'apply', 'render', 'recover',
           'ingest-candidates', 'ingest-clauses', 'ingest-framework',
           'framework-template', 'apply-framework-review', 'batch-build',
           'batch-apply', 'batch-recover', 'batch-refresh', 'batch-template',
           'batch-append-analysis', 'batch-discover', 'batch-retrieve',
           'extract-approved', 'replay-grounding')
CURRENT = ('desktop', 'workbench', 'attention-build', 'attention-apply', 'attention-recover',
           'attention-migrate', 'attention-import-a', 'attention-generate',
           'attention-preview', 'attention-accept')


class CurrentCLI(unittest.TestCase):
    def test_help_and_dispatch_offer_only_current_analysis_and_reject_old_writers_without_mutation(self):
        help_text = io.StringIO()
        with redirect_stdout(help_text), self.assertRaises(SystemExit) as exit:
            main(['--help'])
        self.assertEqual(exit.exception.code, 0)
        choices = help_text.getvalue().split('{', 1)[1].split('}', 1)[0].split(',')
        self.assertEqual(set(choices), set(CURRENT))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'PRIVATE_SOURCE_NAME.json'
            source.write_bytes(b'PRIVATE_RAW_ORIGINAL')
            for command in RETIRED:
                with self.subTest(command=command):
                    output, errors = io.StringIO(), io.StringIO()
                    with redirect_stdout(output), redirect_stderr(errors):
                        result = main([command, str(source), '--workspace', str(root / 'must-not-exist')])
                    self.assertEqual(result, 2)
                    self.assertEqual(errors.getvalue(), 'E_ARGUMENTS\n')
                    self.assertEqual(output.getvalue(), '')
                    self.assertEqual(list(root.iterdir()), [source])
                    self.assertEqual(source.read_bytes(), b'PRIVATE_RAW_ORIGINAL')

    def test_build_apply_replay_and_recover_preserve_raw_evidence_and_original_patch_audit(self):
        from reviewproto.core import digest
        from reviewproto.local_io import encoded
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / 'analysis'
            source = root / 'input.json'
            source.write_text(json.dumps({'schema': 'attention-input/1', 'records': [
                {'anchor': 'B', 'visibility': 'author_visible', 'text': '清晰😀。清晰😀。',
                 'scores': [{'label': '原分', 'raw_value': ' 4.0 / 5 '}]}],
                'a_reference': {'version': 'no-a', 'items': []}}, ensure_ascii=False), encoding='utf-8')
            original = source.read_bytes()
            def cli(command, input_path=None):
                args = [command, '--workspace', str(analysis)]
                if input_path: args.append(str(input_path))
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    code = main(args)
                self.assertEqual(code, 0, errors.getvalue())
                self.assertNotIn('清晰', output.getvalue() + errors.getvalue())
                self.assertNotIn('4.0', output.getvalue() + errors.getvalue())
            cli('attention-build', source)
            with closing(AttentionWorkspace(analysis)) as workspace:
                state = workspace.state()
            record = state['records'][0]
            evidence = [{'source_id': record['source_id'], 'section_id': 'B',
                         'start': 4, 'end': 7, 'quote': '清晰😀'}]
            patch = {'schema': 'attention-patch/1', 'analysis_id': state['analysis_id'],
                     'base_revision': 0, 'actor': '合成编辑', 'reason': '历史草稿仍可回放',
                     'edits': [{'opinion_id': 'O', 'facet_id': 'F', 'record_id': record['record_id'],
                                'evidence': evidence, 'interpretation': '对表达的肯定', 'status': 'working'}]}
            legacy = root / 'legacy.json'; legacy.write_bytes(encoded(patch))
            cli('attention-apply', legacy); cli('attention-apply', legacy)
            current = {'schema': 'attention-patch/2', 'analysis_id': state['analysis_id'],
                       'base_revision': 1, 'actor': '合成复核', 'reason': '补充方面限定',
                       'edits': [{'opinion_id': 'O', 'record_id': record['record_id'],
                                  'interpretation': '保留原分与原话的肯定', 'status': 'working',
                                  'facets': [{'facet_id': 'F', 'evidence': evidence, 'interpretation': '表达清晰',
                                              'status': 'working', 'qualifiers': {'degree': '清晰'}}]}]}
            draft = root / 'current.json'; draft.write_bytes(encoded(current))
            cli('attention-apply', draft); cli('attention-recover'); cli('attention-apply', legacy)
            with closing(AttentionWorkspace(analysis)) as workspace:
                saved = workspace.state()
            self.assertEqual(saved['revision'], 2)
            self.assertEqual(saved['records'][0]['text'], '清晰😀。清晰😀。')
            self.assertEqual(saved['records'][0]['scores'][0]['raw_value'], ' 4.0 / 5 ')
            self.assertEqual(saved['opinions'][0]['facets'][0]['evidence'], evidence)
            self.assertEqual(saved['opinions'][0]['facets'][0]['qualifiers']['degree'], '清晰')
            self.assertEqual([h['patch'] for h in saved['history']], [patch, current])
            self.assertEqual([h['fingerprint'] for h in saved['history']], [digest(encoded(patch)), digest(encoded(current))])
            self.assertEqual(source.read_bytes(), original)
