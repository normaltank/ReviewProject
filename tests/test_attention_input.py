import tempfile
import unittest
from pathlib import Path

from reviewproto.attention import AttentionWorkspace
from reviewproto.desktop import Controller


class OrdinaryAttentionInput(unittest.TestCase):
    def test_a_output_failure_retains_committed_version_and_can_recover(self):
        from reviewproto.attention_input import AttentionInput
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'analysis'
            draft = AttentionInput()
            draft.add_transcription('甲', '普通原话', 'visibility_unknown', [], '第1页')
            controller = Controller(); controller.build_prepared_attention(draft, path)
            html = path / 'attention.html'; html.unlink(); html.mkdir()
            reference = {'version': 'A新版本', 'items': [{'id': 'first', 'text': '可以说明条件', 'locator': '第1项'}]}
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_OUTPUT_RECOVER'):
                controller.import_prepared_attention_a(reference, '合成编辑', '显式采用')
            with self.open(path) as ws:
                self.assertEqual(ws.state()['revision'], 1)
                self.assertEqual(ws.state()['a_reference']['version'], 'A新版本')
            html.rmdir()
            result = controller.recover_attention()
            self.assertEqual(result['revision'], 1)
            self.assertEqual(result['material_status'], 'current')
            self.assertEqual(len(list((path / 'inputs').glob('a-*.json'))), 1)

    def test_material_group_is_optional_metadata_and_does_not_reassign_source_identity(self):
        from reviewproto.attention_input import AttentionInput
        with tempfile.TemporaryDirectory() as tmp:
            states = []
            for group, name in [('材料甲', 'one'), ('材料乙', 'two')]:
                draft = AttentionInput()
                draft.add_transcription('同一锚点', '同一普通原话😀', 'author_visible', [], '同一位置', group)
                path = Path(tmp) / name
                Controller().build_prepared_attention(draft, path)
                with self.open(path) as ws: states.append(ws.state())
            self.assertEqual(states[0]['records'][0]['record_id'], states[1]['records'][0]['record_id'])
            self.assertEqual(states[0]['records'][0]['source_id'], states[1]['records'][0]['source_id'])
            self.assertNotEqual(states[0]['analysis_id'], states[1]['analysis_id'])
            self.assertEqual([s['records'][0]['paper_id'] for s in states], ['材料甲', '材料乙'])

    def test_workspace_ordinary_selection_is_read_only_and_group_conflicts_rejected(self):
        import json
        from reviewproto.attention_input import AttentionInput
        from reviewproto.core import ReviewError
        from reviewproto.store import Workspace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.json'
            source.write_text(json.dumps({'scores': [{'label': '原分', 'raw_value': ' 甲 '}], 'sections': [
                {'section_id': 'ordinary', 'label': '评审意见', 'text': '普通😀'},
                {'section_id': 'second', 'label': '评审意见', 'text': '普通二'},
                {'section_id': 'private', 'label': '其他意见（作者不可见）', 'text': 'PRIVATE_NEVER_COPY'}]}), encoding='utf-8')
            with self.workspace(root / 'source') as ws:
                ws.run(source, 'synthetic', 'json')
            db = root / 'source/review.sqlite3'
            before = db.read_bytes()
            draft = AttentionInput()
            self.assertEqual([s['section_id'] for s in draft.workspace_options(root / 'source')], ['ordinary', 'second'])
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_PRIVATE'):
                draft.add_workspace(root / 'source', 'private')
            draft.add_workspace(root / 'source', 'ordinary', '材料甲')
            draft.add_workspace(root / 'source', 'second', '材料乙')
            controller = Controller()
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_GROUP'):
                controller.build_prepared_attention(draft, root / 'conflict')
            self.assertFalse((root / 'conflict').exists())
            draft.remove(1)
            draft.add_workspace(root / 'source', 'second', '材料甲')
            controller.build_prepared_attention(draft, root / 'analysis')
            with self.open(root / 'analysis') as ws:
                state = ws.state()
                self.assertEqual(len(state['records']), 1)
                self.assertEqual(len(state['records'][0]['sections']), 2)
                self.assertEqual(state['records'][0]['paper_id'], '材料甲')
                self.assertNotIn('PRIVATE_NEVER_COPY', json.dumps(state))
            self.assertEqual(db.read_bytes(), before)

    @staticmethod
    def workspace(path):
        from contextlib import closing
        from reviewproto.store import Workspace
        return closing(Workspace(path))

    def test_existing_file_and_nonempty_directory_never_overwritten(self):
        from reviewproto.attention_input import AttentionInput
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = AttentionInput()
            draft.add_transcription('甲', '原话', 'author_visible', [], '第1页')
            file = root / 'file'; file.write_bytes(b'original')
            folder = root / 'folder'; folder.mkdir(); (folder / 'original').write_bytes(b'original')
            controller = Controller()
            for target in (file, folder):
                with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_NOT_DEDICATED'):
                    controller.build_prepared_attention(draft, target)
            self.assertEqual(file.read_bytes(), b'original')
            self.assertEqual((folder / 'original').read_bytes(), b'original')
            self.assertIsNone(getattr(controller, 'attention_path', None))

    def test_three_part_a_and_explicit_replacement_keep_b_identity_and_separate_snapshots(self):
        from reviewproto.attention_input import AttentionInput
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = AttentionInput()
            for number in range(3):
                draft.add_transcription(str(number), '合成原话' + str(number), 'author_visible',
                                        [{'label': '自由' + str(i), 'raw_value': ' 值😀 '} for i in range(number)],
                                        '合成页' + str(number), '材料甲')
            draft.set_a({'version': '参照甲', 'parts': [{'id': 'p1', 'label': '第一'}, {'id': 'p2', 'label': '第二'}, {'id': 'empty', 'label': '空部分'}],
                         'items': [{'id': 'a1', 'text': '可以说明条件。', 'locator': '第1项', 'part_id': 'p1'},
                                   {'id': 'a2', 'text': '必要时比较。', 'locator': '第2项', 'part_id': 'p2'},
                                   {'id': 'a3', 'text': '例如说明范围。', 'locator': '第3项', 'part_id': 'p2'}]})
            controller = Controller()
            path = root / 'first'
            controller.build_prepared_attention(draft, path)
            b_bytes = (path / 'inputs/b-input.json').read_bytes()
            with self.open(path) as ws:
                before = ws.state()
                self.assertEqual(len(before['a_reference']['parts']), 3)
                self.assertEqual(before['records'][0]['paper_id'], '材料甲')
                self.assertEqual(before['revision'], 1)
                record = before['records'][0]
                ev = dict(source_id=record['source_id'], section_id=record['anchor'], start=0,
                          end=len(record['text']), quote=record['text'])
                ws.apply(dict(schema='attention-patch/2', analysis_id=before['analysis_id'], base_revision=1,
                              actor='合成编辑', reason='核对关注', edits=[dict(opinion_id='opinion', record_id=record['record_id'],
                              interpretation='条件说明', status='working', facets=[dict(facet_id='facet', interpretation='说明条件',
                              status='working', evidence=[ev], a_links=[dict(a_item_id='a1', version='参照甲', kind='related',
                              scope='条件', reason='内容相关', evidence=[ev], status='working')])])]))
                before = ws.state()
            new_a = {'version': '参照乙', 'parts': [], 'items': [{'id': 'new', 'text': '往往关注背景。', 'locator': '新第1项'}]}
            controller.import_prepared_attention_a(new_a, '合成编辑', '明确换版')
            with self.open(path) as ws:
                after = ws.state()
                self.assertEqual(after['analysis_id'], before['analysis_id'])
                self.assertEqual(after['records'], before['records'])
                self.assertEqual(after['a_reference_history'][-1]['a_reference'], draft.a_reference)
                self.assertEqual(after['b_material_status'], 'current')
                self.assertEqual(after['opinions'][0]['opinion_id'], 'opinion')
                self.assertEqual(after['opinions'][0]['facets'][0]['a_links'][0]['status'], 'needs_review')
                current_a = next(b for b in after['bindings'] if b.get('role') == 'a_reference')
                a_path = Path(current_a['path'])
                a_bytes = a_path.read_bytes(); a_path.write_bytes(a_bytes + b'\n')
                self.assertEqual(ws.state()['b_material_status'], 'current')
                self.assertEqual(ws.state()['a_material_status'], 'needs_revalidation')
                a_path.write_bytes(a_bytes)
            self.assertEqual((path / 'inputs/b-input.json').read_bytes(), b_bytes)
            self.assertEqual(len(list((path / 'inputs').glob('a-*.json'))), 2)

    def test_invalid_checklist_protects_destination_and_current_package(self):
        from reviewproto.attention_input import AttentionInput
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = AttentionInput()
            draft.add_transcription('甲', '原话', 'author_visible', [], '第1页')
            controller = Controller()
            controller.build_prepared_attention(draft, root / 'old')
            draft.records.append(dict(draft.records[0]))
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_DUPLICATE'):
                controller.build_prepared_attention(draft, root / 'invalid')
            self.assertFalse((root / 'invalid').exists())
            self.assertEqual(controller.attention_path, root / 'old')

    def test_two_records_without_a_preserve_unicode_and_free_scores_in_new_package(self):
        from reviewproto.attention_input import AttentionInput
        with tempfile.TemporaryDirectory() as tmp:
            draft = AttentionInput()
            draft.add_transcription('甲😀', ' 清晰😀。清晰😀。\n第二行 ', 'visibility_unknown',
                                    [{'label': '任意 / α', 'raw_value': ' 甲级 3.50 '}], '合成表第1格')
            draft.add_transcription('乙', '建议补充条件。', 'author_visible', [], '合成第2页')
            path = Path(tmp) / 'analysis'
            result = Controller().build_prepared_attention(draft, path)
            with self.open(path) as ws:
                state = ws.state()
                self.assertEqual(result['revision'], 0)
                self.assertEqual(len(state['records']), 2)
                self.assertEqual(state['records'][0]['text'], ' 清晰😀。清晰😀。\n第二行 ')
                self.assertEqual(state['records'][0]['scores'], [{'label': '任意 / α', 'raw_value': ' 甲级 3.50 '}])
                self.assertEqual(state['records'][1]['scores'], [])
                self.assertEqual(state['a_reference']['items'], [])
                self.assertEqual(state['opinions'], [])
                self.assertEqual(state['material_status'], 'current')
                self.assertTrue((path / 'inputs' / 'b-input.json').is_file())

    @staticmethod
    def open(path):
        from contextlib import closing
        return closing(AttentionWorkspace(path))
