import tempfile
import unittest
from pathlib import Path
from reviewproto.attention import AttentionWorkspace

class AttentionRoundtrip(unittest.TestCase):
    def test_evidence_interpretation_survives_apply_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'analysis'
            ws = AttentionWorkspace(path)
            ws.build({'schema': 'attention-input/1', 'records': [{'anchor': 'R1', 'visibility': 'author_visible', 'text': '清晰😀。清晰😀。', 'scores': [{'label': '原分', 'raw_value': ' 4.0 '}]}], 'a_reference': {'version': 'synthetic-a1', 'items': [{'id': 'A1', 'text': '可以关注结构', 'locator': '合成第1项'}]}}, base=Path(tmp))
            record = ws.state()['records'][0]
            patch = {'schema': 'attention-patch/1', 'analysis_id': ws.state()['analysis_id'], 'base_revision': 0, 'actor': '合成编辑', 'reason': '根据重复句的第二处创建解释', 'edits': [{'opinion_id': 'op1', 'facet_id': 'f1', 'record_id': record['record_id'], 'evidence': [{'source_id': record['source_id'], 'section_id': 'R1', 'start': 4, 'end': 7, 'quote': '清晰😀'}], 'interpretation': '对结构的肯定', 'status': 'working'}]}
            ws.apply(patch)
            ws.close()
            ws = AttentionWorkspace(path)
            state = ws.recover()
            self.assertEqual(state['revision'], 1)
            self.assertEqual(state['opinions'][0]['interpretation'], '对结构的肯定')
            self.assertEqual(state['records'][0]['scores'][0]['raw_value'], ' 4.0 ')
            self.assertEqual(state['opinions'][0]['evidence'][0]['start'], 4)
            self.assertTrue((path / 'attention.html').exists())
            ws.close()


class AttentionAcceptance(unittest.TestCase):
    def setUp(self):
        import json
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'analysis'
        self.input = self.root / 'input.json'
        self.payload = json.loads((Path(__file__).parent / 'fixtures/synthetic_attention_input.json').read_text(encoding='utf-8'))
        self.input.write_text(json.dumps(self.payload, ensure_ascii=False), encoding='utf-8')

    def patch(self, state):
        r = state['records'][0]
        return {'schema': 'attention-patch/1', 'analysis_id': state['analysis_id'], 'base_revision': state['revision'], 'actor': '合成编辑', 'reason': '核对第二次出现', 'edits': [{'opinion_id': 'op1', 'facet_id': 'f1', 'record_id': r['record_id'], 'evidence': [{'source_id': r['source_id'], 'section_id': r['sections'][0]['section_id'], 'start': 4, 'end': 7, 'quote': '清晰😀'}], 'interpretation': '结构肯定', 'status': 'working'}]}

    def test_bad_multi_edit_is_atomic_conflicts_and_replay_do_not_create_history(self):
        import copy
        from reviewproto.core import ReviewError
        ws = AttentionWorkspace(self.path); self.addCleanup(ws.close)
        state = ws.build(input_path=self.input)
        good = self.patch(state)
        bad = copy.deepcopy(good)
        bad['edits'].append(dict(copy.deepcopy(good['edits'][0]), opinion_id='op2', facet_id='f2'))
        bad['edits'][1]['evidence'][0]['quote'] = '错'
        with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_QUOTE'):
            ws.apply(bad)
        self.assertEqual(ws.state()['revision'], 0)
        self.assertEqual(ws.state()['opinions'], [])
        self.assertEqual(ws.state()['history'], [])
        ws.apply(good); ws.apply(good)
        self.assertEqual(len(ws.state()['history']), 1)
        stale = copy.deepcopy(good); stale['reason'] = '另一次修改'
        with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_CONFLICT') as failure:
            ws.apply(stale)
        from reviewproto.desktop import safe_message
        self.assertIn('过期', safe_message(failure.exception))
        self.assertIn('恢复关注页', safe_message(failure.exception))
        for key, value, error in [('source_id', 'wrong', 'E_ATTENTION_QUOTE'), ('start', -1, 'E_ATTENTION_RANGE'), ('section_id', 'wrong', 'E_ATTENTION_SECTION')]:
            patch = self.patch(ws.state()); patch['edits'][0]['evidence'][0][key] = value
            with self.assertRaisesRegex(ReviewError, error):
                ws.apply(patch)
        self.assertEqual(ws.state()['revision'], 1)

    def test_commit_then_output_failure_recovers_without_duplicate_revision(self):
        from reviewproto.core import ReviewError
        from reviewproto.desktop import Controller, safe_message
        import json
        ws = AttentionWorkspace(self.path); self.addCleanup(ws.close)
        state = ws.build(input_path=self.input); patch = self.patch(state)
        controller = Controller(); controller.open_attention(self.path)
        patch_path = self.root / 'patch.json'
        patch_path.write_text(json.dumps(patch), encoding='utf-8')
        html = self.path / 'attention.html'; html.unlink(); html.mkdir()
        with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_OUTPUT_RECOVER') as failure:
            controller.apply_attention(patch_path)
        self.assertIn('恢复关注页', safe_message(failure.exception))
        self.assertEqual(ws.state()['revision'], 1)
        html.rmdir(); ws.recover(); ws.apply(patch)
        self.assertEqual(ws.state()['revision'], 1)
        self.assertEqual(len(ws.state()['history']), 1)
        import shutil
        ws.close()
        backup = self.root / 'restored-copy'
        shutil.copytree(self.path, backup)
        restored = AttentionWorkspace(backup)
        try:
            recovered = restored.recover()
            self.assertEqual(recovered['revision'], 1)
            self.assertEqual(recovered['opinions'][0]['opinion_id'], 'op1')
            self.assertEqual(len(recovered['history']), 1)
        finally:
            restored.close()

    def test_workspace_selection_is_read_only_private_free_and_groups_sections(self):
        import json
        from reviewproto.store import Workspace
        from reviewproto.core import ReviewError, digest
        source_input = self.root / 'source.json'
        source_input.write_text(json.dumps({'scores': [{'label': '分数', 'raw_value': ' 4 '}], 'sections': [{'section_id': 's1', 'label': '评审意见', 'text': '清晰😀。清晰😀。'}, {'section_id': 's2', 'label': '评审意见', 'text': '第二普通分区'}, {'section_id': 'private', 'label': '其他意见（作者不可见）', 'text': 'PRIVATE_NEVER_COPY'}]}), encoding='utf-8')
        src = Workspace(self.root / 'source'); src.run(source_input, 'synthetic', 'json'); src.close()
        database = self.root / 'source/review.sqlite3'; before = database.read_bytes()
        self.payload['records'] = [{'kind': 'workspace', 'workspace': 'source', 'section_id': sid} for sid in ('s1', 's2')]
        ws = AttentionWorkspace(self.path); self.addCleanup(ws.close)
        state = ws.build(self.payload, base=self.root)
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(len(state['records']), 1)
        self.assertEqual(len(state['records'][0]['sections']), 2)
        self.assertNotIn('PRIVATE_NEVER_COPY', json.dumps(state))
        self.assertEqual(state['records'][0]['scores'][0]['raw_value'], ' 4 ')
        ws.apply(self.patch(state)); ws.recover()
        self.assertEqual(database.read_bytes(), before)
        bad = AttentionWorkspace(self.root / 'bad'); self.addCleanup(bad.close)
        self.payload['records'][0]['section_id'] = 'private'
        with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_PRIVATE'):
            bad.build(self.payload, base=self.root)
        self.assertNotIn('PRIVATE_NEVER_COPY', (self.path / 'attention-state.json').read_text(encoding='utf-8'))

    def test_changed_input_keeps_frozen_snapshot_and_blocks_edits(self):
        from reviewproto.core import ReviewError
        ws = AttentionWorkspace(self.path); self.addCleanup(ws.close)
        before = ws.build(input_path=self.input)
        self.input.write_text('{}', encoding='utf-8')
        state = ws.recover()
        self.assertEqual(state['material_status'], 'needs_revalidation')
        self.assertEqual(state['records'], before['records'])
        with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_REVALIDATION') as failure:
            ws.apply(self.patch(before))
        from reviewproto.desktop import safe_message
        self.assertIn('来源或A参照待核', safe_message(failure.exception))
        self.assertIn('恢复关注页', safe_message(failure.exception))

    def test_browser_form_download_cli_apply_controller_reopen_and_edit(self):
        import json, os, subprocess, sys
        from playwright.sync_api import sync_playwright
        from reviewproto.desktop import Controller
        from reviewproto.store import encoded
        evidence_dir = Path(os.environ.get('ATTENTION_EVIDENCE_DIR', self.root / 'screens'))
        evidence_dir.mkdir(parents=True, exist_ok=True)
        def cli(command, source=None):
            args = [sys.executable, '-m', 'reviewproto', command, '--workspace', str(self.path)]
            if source: args.append(str(source))
            done = subprocess.run(args, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertNotIn('清晰', done.stdout + done.stderr)
        cli('attention-build', self.input)
        controller = Controller(); result = controller.open_attention(self.path)
        self.assertEqual(result['kind'], 'attention'); self.assertIsNone(controller.path)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY', 'C:/Program Files/Google/Chrome/Application/chrome.exe'), headless=True)
            page = browser.new_page(accept_downloads=True, offline=True, viewport={'width': 1440, 'height': 1000})
            page.on('dialog', lambda d: d.accept())
            page.goto((self.path / 'attention.html').as_uri())
            errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
            page.locator('#stage').click()
            self.assertIn('请选择原话证据', page.locator('#message').inner_text())
            page.locator('#passage').focus(); page.keyboard.press('End'); page.keyboard.press('Enter')
            page.locator('#interpretation').fill('对结构清晰的肯定（合成）')
            self.assertIn('未加入草稿', page.locator('#draft').inner_text())
            page.locator('#actor').fill('合成浏览器编辑'); page.locator('#reason').fill('根据第二处原话')
            page.locator('#stage').click()
            self.assertIn('未应用草稿：1项', page.locator('#draft').inner_text())
            for width, filename in [(1440, 'desktop-draft.png'), (420, 'mobile-draft.png')]:
                page.set_viewport_size({'width': width, 'height': 1000})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                page.screenshot(path=str(evidence_dir / filename), full_page=True)
            with page.expect_download() as download:
                page.locator('#download').click()
            patchfile = self.root / 'draft.json'; download.value.save_as(patchfile)
            patch = json.loads(patchfile.read_text(encoding='utf-8'))
            self.assertEqual(patch['edits'][0]['evidence'][0]['start'], 4)
            self.assertIn('尚未应用保存', page.locator('#message').inner_text())
            cli('attention-apply', patchfile); cli('attention-recover')
            page.reload()
            self.assertIn('已保存修订 1', page.locator('#revision').inner_text())
            if not page.locator('#saved').is_visible():
                page.get_by_text('展开全部保存解释与撤回/替换历史（不随上方筛选）', exact=True).click()
            self.assertIn('对结构清晰的肯定', page.locator('#saved').inner_text())
            oid = patch['edits'][0]['opinion_id']; page.locator('#opinion').select_option(oid)
            page.locator('#interpretation').fill('纠正后的结构肯定（合成）')
            page.locator('#actor').fill('合成编辑'); page.locator('#reason').fill('修正解释')
            page.locator('#stage').click()
            with page.expect_download() as download:
                page.locator('#download').click()
            download.value.save_as(patchfile)
            self.assertEqual(controller.apply_attention(patchfile)['revision'], 2)
            controller.recover_attention(); page.reload()
            if not page.locator('#saved').is_visible():
                page.get_by_text('展开全部保存解释与撤回/替换历史（不随上方筛选）', exact=True).click()
            self.assertIn('纠正后的结构肯定', page.locator('#saved').inner_text())
            for width, filename in [(1440, 'desktop-saved.png'), (420, 'mobile-saved.png')]:
                page.set_viewport_size({'width': width, 'height': 1000})
                page.screenshot(path=str(evidence_dir / filename), full_page=True)
            self.assertEqual(errors, [])
            browser.close()

    def test_reordered_input_and_new_analysis_run_preserve_record_identities(self):
        import copy
        first = AttentionWorkspace(self.path); self.addCleanup(first.close)
        payload = copy.deepcopy(self.payload)
        payload['records'].append(dict(copy.deepcopy(payload['records'][0]), anchor='R2', text='另一个合成记录'))
        initial = first.build(payload, base=self.root)
        payload['records'].reverse()
        second = AttentionWorkspace(self.root / 'second'); self.addCleanup(second.close)
        reordered = second.build(payload, base=self.root)
        self.assertNotEqual(initial['analysis_id'], reordered['analysis_id'])
        self.assertEqual({r['anchor']: r['record_id'] for r in initial['records']}, {r['anchor']: r['record_id'] for r in reordered['records']})

        from reviewproto.desktop import Controller
        controller = Controller()
        result = controller.build_attention(self.input, self.root / 'controller-created')
        self.assertEqual(result['revision'], 0)
        self.assertEqual(result['kind'], 'attention')
        self.assertIsNone(controller.path)

    def test_transcription_preserves_declared_public_visibility_and_refuses_private_or_undeclared(self):
        import copy
        from reviewproto.core import ReviewError
        for visibility in ('author_visible', 'visibility_unknown'):
            with self.subTest(visibility=visibility):
                payload = copy.deepcopy(self.payload)
                payload['records'][0]['visibility'] = visibility
                ws = AttentionWorkspace(self.root / visibility)
                try:
                    state = ws.build(payload, base=self.root)
                    self.assertEqual(state['records'][0]['visibility'], visibility)
                    self.assertEqual(state['records'][0]['text'], '清晰😀。清晰😀。')
                finally:
                    ws.close()
        for index, visibility in enumerate(('internal_only', None, 'invalid')):
            with self.subTest(rejected=visibility):
                payload = copy.deepcopy(self.payload)
                if visibility is None:
                    payload['records'][0].pop('visibility')
                else:
                    payload['records'][0]['visibility'] = visibility
                ws = AttentionWorkspace(self.root / ('rejected-' + str(index)))
                try:
                    with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_PRIVATE'):
                        ws.build(payload, base=self.root)
                    with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_EMPTY'):
                        ws.state()
                finally:
                    ws.close()
