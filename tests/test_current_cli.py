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
CURRENT = ('desktop', 'attention-build', 'attention-apply', 'attention-recover',
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
