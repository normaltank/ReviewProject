import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_input import AttentionInput, build_prepared
from legacy_source_fixture import create_legacy_workspace


class LegacySourceReading(unittest.TestCase):
    def test_import_ordinary_review_ignores_broken_framework_without_changing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'legacy'
            create_legacy_workspace(source, revision=7, state_updates={
                'frameworks': [{'sha256': 'broken', 'book': {'no_longer_supported': True}}],
                'candidates': [{'obsolete': 'NEVER_COPY_CANDIDATES'}]})
            framework = source / 'frameworks/broken/book.json'
            framework.parent.mkdir(parents=True)
            framework.write_bytes(b'not valid json')
            before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            draft = AttentionInput()
            self.assertEqual([s['section_id'] for s in draft.workspace_options(source)], ['ordinary'])
            draft.add_workspace(source, 'ordinary')
            build_prepared(draft, root / 'analysis')
            with closing(AttentionWorkspace(root / 'analysis')) as ws:
                state = ws.state()
                self.assertEqual(state['material_status'], 'current')
                self.assertEqual(state['records'][0]['text'], '普通😀。若不能补证，可降低结论。')
                self.assertEqual(state['records'][0]['scores'][0]['raw_value'], ' 3.50 ')
                self.assertEqual(next(b for b in state['bindings'] if b['kind'] == 'workspace')['revision'], 7)
                self.assertNotIn('PRIVATE_NEVER_COPY', json.dumps(state))
                self.assertNotIn('NEVER_COPY_CANDIDATES', json.dumps(state))
            self.assertEqual({p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}, before)



    def test_source_reader_exposes_only_material_and_revision(self):
        from reviewproto.legacy_source import read_source_workspace
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source'
            create_legacy_workspace(path, revision=4, state_updates={'candidates': [{'stale': True}], 'decisions': [{'old': True}]})
            state = read_source_workspace(path)
            self.assertEqual(set(state), {'source', 'revision', 'scores', 'sections'})
            self.assertEqual(state['revision'], 4)
            self.assertEqual(state['scores'][0]['raw_value'], ' 3.50 ')
            self.assertEqual(state['sections'][0]['text'], '普通😀。若不能补证，可降低结论。')

    def test_changed_original_preserves_saved_analysis_but_blocks_new_edits(self):
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            create_legacy_workspace(source)
            draft = AttentionInput()
            draft.add_workspace(source, 'ordinary')
            build_prepared(draft, root / 'analysis')
            original = source / 'source.json'
            original.write_bytes(original.read_bytes() + b' ')
            with self.assertRaisesRegex(ReviewError, 'E_SOURCE_CHANGED'):
                AttentionInput.workspace_options(source)
            with closing(AttentionWorkspace(root / 'analysis')) as ws:
                state = ws.state()
                self.assertEqual(state['material_status'], 'needs_revalidation')
                self.assertEqual(state['records'][0]['text'], '普通😀。若不能补证，可降低结论。')
                with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_REVALIDATION'):
                    ws.apply({'schema': 'attention-patch/2', 'analysis_id': state['analysis_id'],
                              'base_revision': 0, 'actor': '合成编辑', 'reason': '不覆盖旧分析',
                              'themes': [{'theme_id': 't', 'label': '说明', 'definition': '', 'parent_ids': [], 'status': 'working'}]})
                self.assertEqual(ws.state()['revision'], 0)

    def test_current_parser_rejects_corrupt_original_even_if_stored_hash_matches(self):
        from reviewproto.core import ReviewError, digest
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source'
            bad = b'not a valid original json'
            create_legacy_workspace(path, state_updates={
                'source': {'kind': 'structured_json', 'sha256': digest(bad), 'source_id': digest(bad)}})
            (path / 'source.json').write_bytes(bad)
            with self.assertRaisesRegex(ReviewError, 'E_STRUCTURED_JSON'):
                AttentionInput.workspace_options(path)

    def test_saved_scores_sections_and_source_identity_must_match_reparsed_original(self):
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for field in ('scores', 'sections', 'source_id'):
                with self.subTest(field=field):
                    path = root / field
                    state = create_legacy_workspace(path)
                    if field == 'scores': state['scores'][0]['raw_value'] = '5'
                    elif field == 'sections': state['sections'][0]['text'] = '伪造旧缓存'
                    else: state['source']['source_id'] = 'a' * 64
                    replace_state(path, state)
                    with self.assertRaisesRegex(ReviewError, 'E_REIMPORT_REQUIRED'):
                        AttentionInput.workspace_options(path)

    def test_private_selection_rejected_at_input_and_analysis_interfaces(self):
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            create_legacy_workspace(source)
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_PRIVATE'):
                AttentionInput().add_workspace(source, 'private')
            with closing(AttentionWorkspace(root / 'analysis')) as ws:
                with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_PRIVATE'):
                    ws.build({'schema': 'attention-input/1', 'records': [
                        {'kind': 'workspace', 'workspace': str(source), 'section_id': 'private'}],
                        'a_reference': {'version': 'no-a', 'items': []}})

    def test_foreign_database_or_invalid_historical_schema_rejected(self):
        import sqlite3
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for problem, expected in [('foreign', 'E_BATCH_SOURCE'), ('schema', 'E_SCHEMA_VERSION'), ('tables', 'E_BATCH_SOURCE')]:
                with self.subTest(problem=problem):
                    path = root / problem
                    state = create_legacy_workspace(path)
                    if problem == 'schema':
                        state['schema_version'] = 'foreign/1'
                        replace_state(path, state)
                    else:
                        with closing(sqlite3.connect(path / 'review.sqlite3')) as db:
                            db.execute('PRAGMA application_id=99' if problem == 'foreign' else 'DROP TABLE runs')
                            db.commit()
                    before = (path / 'review.sqlite3').read_bytes()
                    with self.assertRaisesRegex(ReviewError, expected):
                        AttentionInput.workspace_options(path)
                    self.assertEqual((path / 'review.sqlite3').read_bytes(), before)

    def test_fixed_source_filename_cannot_select_another_local_file(self):
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source'
            state = create_legacy_workspace(path)
            state['source']['storage_file'] = '../other.json'
            replace_state(path, state)
            with self.assertRaisesRegex(ReviewError, 'E_SOURCE_KIND'):
                AttentionInput.workspace_options(path)

    def test_linked_original_or_database_rejected(self):
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in ('source.json', 'review.sqlite3'):
                with self.subTest(filename=filename):
                    path = root / filename.replace('.', '-')
                    create_legacy_workspace(path)
                    frozen = path / filename
                    outside = root / ('outside-' + filename)
                    frozen.replace(outside)
                    try:
                        frozen.symlink_to(outside)
                    except OSError:
                        self.skipTest('host cannot create symlinks')
                    with self.assertRaisesRegex(ReviewError, 'E_BATCH_LINK'):
                        AttentionInput.workspace_options(path)

    def test_oversize_original_is_rejected_without_replacing_source(self):
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source'
            create_legacy_workspace(path)
            original = path / 'source.json'
            with original.open('ab') as stream:
                stream.truncate(40_000_001)
            before = original.stat().st_size
            with self.assertRaisesRegex(ReviewError, 'E_INPUT_LIMIT'):
                AttentionInput.workspace_options(path)
            self.assertEqual(original.stat().st_size, before)

    def test_unsupported_native_original_cannot_hide_in_cache_or_erase_human_history(self):
        from reviewproto.core import ReviewError, digest
        from native_source_fixture import fixture, native_variant
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            history = [{'actor': '合成编辑', 'reason': '旧人工记录', 'value': 'SAVED_HUMAN_VALUE'}]
            state = create_legacy_workspace(source, data=fixture(), kind='native_docx',
                                            revision=3, state_updates={'decisions': history})
            unsupported = native_variant('oMath', 'comment')
            source_id = digest(unsupported)
            state['source'].update(source_id=source_id, sha256=source_id)
            for section in state['sections']: section['source_id'] = source_id
            state['versions']['parser'] = 'verified-two-cell-v1'
            replace_state(source, state)
            (source / 'source.docx').write_bytes(unsupported)
            before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ReviewError, 'E_UNSUPPORTED_FEATURE'):
                AttentionInput.workspace_options(source)
            self.assertEqual({p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}, before)

    def test_structured_json_and_csv_originals_keep_raw_scores_unicode_and_fixed_locations(self):
        import csv
        import io
        from reviewproto.core import SCORE_NAMES, ReviewError
        rows = [['期刊名称', 'synthetic journal', '稿件ID', 'SYNTHETIC-ID', '投稿日期', 'synthetic date'],
                ['稿件标题', 'synthetic title', '', '', '', ''],
                [SCORE_NAMES[0], '4', SCORE_NAMES[1], '4', SCORE_NAMES[2], '4'],
                [SCORE_NAMES[3], ' 3.0 ', '', '', '', ''],
                ['评审意见', '样本规模不足。\n另一段😀', '', '', '', ''],
                ['其他意见（作者不可见）', 'PRIVATE_NEVER_COPY', '', '', '', '']]
        stream = io.StringIO(newline=''); csv.writer(stream).writerows(rows)
        structured = {'scores': [{'label': '自定义原分', 'raw_value': ' 甲 4.0 '}],
                      'sections': [{'section_id': 'ordinary', 'label': '评审意见', 'text': '结构化合成评论😀'}]}
        cases = [('structured_csv', stream.getvalue().encode('utf-8-sig'), 'section-1', 'source.csv',
                  ['4', '4', '4', ' 3.0 '], '样本规模不足。\n另一段😀', {'row': 4, 'cell': 1}),
                 ('structured_json', json.dumps(structured, ensure_ascii=False).encode(), 'ordinary', 'source.json',
                  [' 甲 4.0 '], '结构化合成评论😀', {'pointer': '/sections/0/text'})]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for kind, content, section, filename, scores, text, locator in cases:
                with self.subTest(kind=kind):
                    source = root / kind
                    create_legacy_workspace(source, data=content, kind=kind)
                    draft = AttentionInput(); draft.add_workspace(source, section)
                    before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
                    build_prepared(draft, root / (kind + '-analysis'))
                    with closing(AttentionWorkspace(root / (kind + '-analysis'))) as workspace:
                        state = workspace.state()
                        record = state['records'][0]
                        self.assertEqual([s['raw_value'] for s in record['scores']], scores)
                        self.assertEqual(record['text'], text)
                        self.assertEqual(record['sections'][0]['locator'], locator)
                        self.assertNotIn('PRIVATE_NEVER_COPY', json.dumps(state))
                        self.assertEqual({p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}, before)
                        (source / filename).write_bytes(content + b' ')
                        self.assertEqual(workspace.state()['material_status'], 'needs_revalidation')
                        self.assertEqual(workspace.state()['records'], state['records'])


def replace_state(path, state):
    import sqlite3
    with closing(sqlite3.connect(path / 'review.sqlite3')) as db:
        db.execute('UPDATE state SET payload=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))
        db.commit()
