"""Public workspace opening preserves protection and releases failed resources."""
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from reviewproto.attention import AttentionWorkspace
from reviewproto.local_io import PRIVATE_IGNORE


class WorkspaceOpenTests(unittest.TestCase):
    def build(self, path):
        with closing(AttentionWorkspace(path)) as workspace:
            return workspace.build({'schema': 'attention-input/1', 'records': [
                {'anchor': 's', 'visibility': 'author_visible', 'text': '图例已经明确。'}],
                'a_reference': {'version': 'none', 'items': []}})

    def test_open_with_protection_reader_preserves_file_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'pack'
            expected = self.build(path)
            protection = path/'.gitignore'
            os.utime(protection, ns=(1600000000000000000, 1600000000000000000))
            before = protection.stat()
            with protection.open('rb') as reader:
                with closing(AttentionWorkspace(path)) as workspace:
                    self.assertEqual(workspace.state(), expected)
                    self.assertEqual(reader.read(), PRIVATE_IGNORE)
                after = protection.stat()
                self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))
            self.assertEqual(protection.read_bytes(), PRIVATE_IGNORE)

    def test_missing_or_incorrect_protection_is_repaired_without_state_change(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'pack'
                expected = self.build(path)
                protection = path/'.gitignore'
                if missing:
                    protection.unlink()
                else:
                    protection.write_bytes(b'# incorrect protection\n')
                with closing(AttentionWorkspace(path)) as workspace:
                    self.assertEqual(workspace.state(), expected)
                    self.assertEqual(protection.read_bytes(), PRIVATE_IGNORE)

    def test_failed_protection_repair_releases_database_without_garbage_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'pack'
            expected = self.build(path)
            protection = path/'.gitignore'
            protection.write_bytes(b'# incorrect protection\n')
            target = protection.resolve()
            replace = os.replace
            def denied(source, destination):
                if Path(destination).resolve() == target:
                    raise PermissionError('synthetic protection repair denied')
                return replace(source, destination)
            failure = None
            with patch('os.replace', side_effect=denied):
                try:
                    unexpected = AttentionWorkspace(path)
                except PermissionError as error:
                    # Keep the exception/traceback alive: cleanup must not depend
                    # on SQLite's connection cycle being garbage-collected.
                    failure = error
                else:
                    unexpected.close()
            self.assertIsInstance(failure, PermissionError)
            self.assertEqual(str(failure), 'synthetic protection repair denied')
            self.assertEqual(protection.read_bytes(), b'# incorrect protection\n')
            self.assertEqual(list(path.glob('.gitignore.*.tmp')), [])
            database = path/'attention.sqlite3'
            moved = database.rename(path/'closed.sqlite3')
            moved.rename(database)
            with closing(AttentionWorkspace(path)) as workspace:
                self.assertEqual(workspace.state(), expected)
                self.assertEqual(protection.read_bytes(), PRIVATE_IGNORE)


if __name__ == '__main__':
    unittest.main()
