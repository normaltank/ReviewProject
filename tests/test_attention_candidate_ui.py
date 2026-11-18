"""Ordinary candidate workflow; replay is engineering verification only."""
from attention_browser import open_panel
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import ReplayProvider


def prepare(path):
    with closing(AttentionWorkspace(path)) as ws:
        state = ws.build({'schema': 'attention-input/1', 'records': [
            {'anchor': 's', 'text': '若有记录，请标明图例。', 'visibility': 'author_visible'}],
            'a_reference': {'version': 'none', 'items': []}})
    record = state['records'][0]
    evidence = dict(source_id=record['source_id'], section_id='s', start=0, end=12,
                    quote='若有记录，请标明图例。')
    evidence['end'] = len(evidence['quote'])
    response = {'edits': [dict(opinion_id='o', record_id=record['record_id'],
        interpretation='有条件地补充图例', status='needs_review', facets=[dict(
            facet_id='f', interpretation='标明图例', status='needs_review', evidence=[evidence],
            qualifiers={'conditions': '若有记录'})])], 'themes': [], 'relations': []}
    return state, response


class CandidateWorkflow(unittest.TestCase):


    def test_generation_checks_the_actual_snapshot_and_frozen_fingerprints(self):
        from unittest.mock import patch
        from reviewproto import attention_candidates as candidates
        from reviewproto.attention_candidate_service import CandidateSession
        from reviewproto.attention_input import import_prepared_a
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'pack'
            state, response = prepare(path)
            session = CandidateSession(path)
            hashes = candidates._adapter_hashes()
            manifest = root / 'adapter-hashes.json'
            manifest.write_text(json.dumps({'schema': 'attention-adapter-hashes/1', 'files': hashes}))
            with patch.object(candidates.sys, 'frozen', True, create=True), patch.object(
                    candidates, '__file__', str(root / 'attention_candidates.py')):
                run = session.generate('frozen', ReplayProvider([response]))
                self.assertEqual(run['adapter_hash'], hashes['attention_candidates.py'])
                self.assertEqual(run['provider_adapter_hash'], hashes['attention_provider.py'])
                self.assertEqual(run['semantic_adapter_hash'], hashes['attention_semantic.py'])
                manifest.unlink()
                with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_ADAPTER_HASHES'):
                    session.generate('missing-manifest', ReplayProvider([]))
            with closing(AttentionWorkspace(path)) as ws:
                import_prepared_a(ws, {'version': 'new', 'items': [
                    {'id': 'a', 'text': '合成新A', 'locator': '第一项'}]}, '测试', '变更A')
            provider = ReplayProvider([])
            with patch.object(provider, 'complete') as complete:
                with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_TARGET'):
                    session.generate('stale', provider)
                complete.assert_not_called()
            self.assertFalse((path / 'candidate-runs' / 'stale').exists())
            self.assertEqual(run['snapshot']['revision'], state['revision'])

    def test_new_candidate_sessions_generate_and_preview_preserve_formal_file_bytes(self):
        from reviewproto.attention_candidate_service import CandidateSession
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pack';prepare(path)
            files=('attention.sqlite3','attention-state.json','attention.html','.gitignore')
            def formal_bytes(): return {name:(path/name).read_bytes() for name in files}
            # Each operation opens its own workspace connection, as the ordinary
            # UI does. No already-open connection may mask constructor writes.
            _,response=prepare(Path(tmp)/'fixture')
            operations=(('new session',lambda:CandidateSession(path)),
                ('generate',lambda:CandidateSession(path).generate('read-only',ReplayProvider([response]))),
                ('preview',lambda:CandidateSession(path).preview('read-only')))
            for label,operation in operations:
                with self.subTest(operation=label):
                    before=formal_bytes();operation()
                    for name,original in before.items():
                        self.assertTrue((path/name).read_bytes()==original,name+' changed during '+label)
            before=formal_bytes()
            saved=CandidateSession(path).accept('read-only',actor='synthetic editor',reason='explicit acceptance')
            self.assertEqual(saved['revision'],1)
            self.assertNotEqual((path/'attention.sqlite3').read_bytes(),before['attention.sqlite3'])

    def doCleanups(self):
        result = super().doCleanups()
        # Collect destroyed Tcl objects on their owning main thread before a
        # later test starts any worker.
        import gc
        gc.collect()
        return result

    def test_source_or_a_changes_during_generation_make_result_unacceptable(self):
        import threading
        from reviewproto.attention_candidate_service import CandidateSession
        from reviewproto.core import ReviewError
        for change in ('source', 'a'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'pack'
                source = Path(tmp) / 'source.json'
                source.write_text(json.dumps({'schema': 'attention-input/1', 'records': [dict(
                    anchor='s', text='若有记录，请标明图例。', visibility='author_visible')],
                    'a_reference': {'version': 'none', 'items': []}}), encoding='utf-8')
                with closing(AttentionWorkspace(path)) as ws: state = ws.build(input_path=source)
                _, response = prepare(Path(tmp) / 'fixture')
                response['edits'][0]['record_id'] = state['records'][0]['record_id']
                response['edits'][0]['facets'][0]['evidence'][0]['source_id'] = state['records'][0]['source_id']
                session = CandidateSession(path)
                started, finish = threading.Event(), threading.Event()
                class Held(ReplayProvider):
                    def complete(self, request):
                        started.set()
                        if not finish.wait(10): raise RuntimeError('timeout')
                        return super().complete(request)
                outputs = []
                thread = threading.Thread(target=lambda: outputs.append(session.generate('held', Held([response]))))
                thread.start(); self.assertTrue(started.wait(3))
                if change == 'source': source.write_text('{}', encoding='utf-8')
                else:
                    a = Path(tmp) / 'a.json'
                    a.write_text(json.dumps({'schema': 'attention-a-input/1', 'a_reference': {
                        'version': 'new-a', 'items': [dict(id='new', text='展示', locator='synthetic')]}}), encoding='utf-8')
                    with closing(AttentionWorkspace(path)) as ws: ws.import_a(a, actor='editor', reason='new')
                finish.set(); thread.join(10); self.assertFalse(thread.is_alive())
                self.assertEqual(len(outputs), 1)
                self.assertIn('须重新生成', session.preview('held').read_text(encoding='utf-8'))
                with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_REVALIDATION'):
                    session.accept('held', actor='editor', reason='stale')
                with closing(AttentionWorkspace(path)) as ws:
                    self.assertEqual(ws.state()['opinions'], [])


    def test_service_ownership_keeps_launch_paths_and_stops_only_its_run(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from reviewproto.attention_candidate_service import CandidateModelService
        from reviewproto.desktop import ROOT
        from reviewproto.core import ReviewError
        service = CandidateModelService()
        with patch('reviewproto.desktop.run_powershell') as command:
            with self.assertRaisesRegex(ReviewError, 'E_MODEL_NOT_OWNED'):
                service.stop()
            command.assert_not_called()
            with tempfile.TemporaryDirectory() as tmp:
                resource, runtime = Path(tmp) / 'resources', Path(tmp) / 'new-runtime'
                resource.mkdir(); runtime.mkdir()
                run_id = 'a' * 32
                (runtime / 'server-state.json').write_text(json.dumps(dict(pid=123, run_id=run_id,
                    repo_root=str(ROOT), owner='ReviewProject/scripts/local-model/v1')), encoding='utf-8')
                command.return_value = SimpleNamespace(returncode=0, stdout=('Owned PID 123 RUN '+run_id).encode())
                service.start(resource, runtime)
                self.assertIn(str(resource.resolve()), [str(v) for v in command.call_args.args[0]])
                self.assertIn(str(runtime), [str(v) for v in command.call_args.args[0]])
                service.stop()
                args = [str(v) for v in command.call_args.args[0]]
                self.assertEqual(args[-6:], ['-ResourceRoot', str(resource.resolve()), '-RuntimeDir', str(runtime.absolute()), '-ExpectedRunId', run_id])
                self.assertIsNone(service.owned)

    def test_failed_start_keeps_only_new_verified_receipt_for_stop(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from reviewproto.attention_candidate_service import CandidateModelService
        from reviewproto.desktop import ROOT
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Path(tmp); run_id='b'*32
            (runtime/'server-state.json').write_text(json.dumps(dict(pid=321,run_id=run_id,
                repo_root=str(ROOT),owner='ReviewProject/scripts/local-model/v1')),encoding='utf-8')
            for receipt,owns in [('',False),('Owned PID 321 RUN '+'c'*32,False),
                                  ('Owned PID 321 RUN '+run_id,True)]:
                with self.subTest(receipt=receipt), patch('reviewproto.desktop.run_powershell') as command:
                    command.return_value=SimpleNamespace(returncode=1,stdout=receipt)
                    service=CandidateModelService()
                    with self.assertRaisesRegex(ReviewError,'E_LOCAL_MODEL_START'):
                        service.start(runtime,runtime)
                    self.assertEqual(service.owned is not None,owns)
                    if owns:
                        command.return_value=SimpleNamespace(returncode=0,stdout='')
                        service.stop()
                        self.assertEqual(command.call_args.args[0][-1],run_id)
                        self.assertIsNone(service.owned)


    def test_frozen_target_generate_preview_accept_reopen(self):
        from reviewproto.attention_candidate_service import CandidateSession
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pack'
            initial, response = prepare(path)
            session = CandidateSession(path)
            result = session.generate('engineering', ReplayProvider([response]))
            self.assertEqual(result['status'], 'complete')
            self.assertIn('若有记录', session.preview('engineering').read_text(encoding='utf-8'))
            self.assertIn('id="candidate-preview"', session.preview('engineering').read_text(encoding='utf-8'))
            with closing(AttentionWorkspace(path)) as ws:
                self.assertEqual(ws.state()['revision'], 0)
                self.assertEqual(ws.state()['opinions'], [])
            saved = session.accept('engineering', actor='合成编辑', reason='工程回查')
            self.assertEqual(saved['revision'], 1)
            self.assertIn('已在修订 1 保存', session.preview('engineering').read_text(encoding='utf-8'))
            reopened = CandidateSession(path)
            self.assertEqual(reopened.accept('engineering', actor='重复', reason='重放')['revision'], 1)
            with closing(AttentionWorkspace(path)) as ws:
                self.assertEqual(ws.state()['opinions'][0]['facets'][0]['status'], 'needs_review')

    def test_generation_uses_captured_identity_and_rejects_revision_change(self):
        from reviewproto.attention_candidate_service import CandidateSession
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pack'
            state, response = prepare(path)
            session = CandidateSession(path)
            other = CandidateSession(path)
            other.generate('first', ReplayProvider([response]))
            other.accept('first', actor='editor', reason='changed')
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_TARGET'):
                session.generate('late', ReplayProvider([response]))
            self.assertFalse((path / 'candidate-runs' / 'late').exists())

    def test_empty_and_partial_runs_preview_unprocessed_scope_and_recovery(self):
        from reviewproto.attention_candidate_service import CandidateSession, candidate_message
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pack'; state, response = prepare(path)
            session = CandidateSession(path)
            empty = session.generate('empty', ReplayProvider([{'edits': [], 'themes': [], 'relations': []}]))
            self.assertEqual(empty['status'], 'zero_candidates')
            self.assertIn('未生成候选', session.preview('empty').read_text(encoding='utf-8'))
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_NO_CANDIDATES'):
                session.accept('empty', actor='editor', reason='empty')
            response['unprocessed'] = [dict(record_id=state['records'][0]['record_id'], section_id='s', reason='still ambiguous')]
            partial = session.generate('partial', ReplayProvider([response]))
            self.assertEqual(partial['status'], 'partial')
            self.assertIn('未完成：', session.preview('partial').read_text(encoding='utf-8'))
            html = path / 'attention.html'; html.unlink(); html.mkdir()
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_OUTPUT_RECOVER') as caught:
                session.accept('partial', actor='editor', reason='valid draft')
            self.assertIn('可能已经保存', candidate_message(caught.exception))
            html.rmdir()
            with closing(AttentionWorkspace(path)) as ws:
                self.assertEqual(ws.recover()['revision'], 1)
            self.assertEqual(session.accept('partial', actor='editor', reason='retry')['revision'], 1)
            self.assertEqual(session.runs(), ['empty', 'partial'])


    def test_chrome_preview_regions_evidence_and_accept_edit_apply_reopen(self):
        import copy
        import os
        from playwright.sync_api import sync_playwright
        from reviewproto.attention_candidate_service import CandidateSession
        from reviewproto.attention_candidate_render import render_candidate_preview
        from reviewproto.desktop import Controller
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pack'
            initial, response = prepare(path)
            session = CandidateSession(path)
            run = session.generate('engineering', ReplayProvider([response]))
            # Renderer seam: a canonical multi-A candidate, independent of the
            # model wire protocol. Generation/accept below still use actual API.
            mapped = copy.deepcopy(run)
            reference = {'version': 'synthetic-variable-A', 'parts': [{'id': 'part', 'label': '展示'}],
                'items': [dict(id=k, part_id='part', text=t, locator='合成参照')
                          for k, t in [('one', '图示说明'), ('two', '呈现完整性')]]}
            mapped['snapshot']['a_reference'] = reference
            facet = mapped['patch']['edits'][0]['facets'][0]
            facet['a_links'] = [dict(a_item_id=k, version=reference['version'], kind='related',
                scope='仅图例', reason='两处相关而非确认覆盖', evidence=facet['evidence'], status='needs_review') for k in ('one', 'two')]
            mapped['validity'] = 'current'
            mapped_html = Path(tmp) / 'mapped.html'
            mapped_html.write_text(render_candidate_preview(mapped), encoding='utf-8')
            preview_path = session.preview('engineering')
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
                page = browser.new_page(offline=True, viewport={'width': 1440, 'height': 1000})
                page.set_default_timeout(6000)
                errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(mapped_html.as_uri())
                page.get_by_role('link', name='查看分布图', exact=True).click()
                open_panel(page, 'view-filters')
                overlay = page.locator('#candidate-position-overlay')
                self.assertIn('尚未保存，全部待核', overlay.inner_text())
                self.assertEqual(overlay.locator('[data-candidate-region="item:one"]').count(), 1)
                self.assertEqual(overlay.locator('[data-candidate-region="item:two"]').count(), 1)
                self.assertIn('1/1', overlay.inner_text())
                self.assertEqual(page.locator('#view-hits').inner_text(), '')
                overlay.locator('svg a[href^="#candidate-facet-"]').first.click()
                self.assertTrue(page.locator('[id^="candidate-facet-"]').first.evaluate('(e)=>e.open'))
                overlay.locator('[data-candidate-region="item:one"]').focus()
                page.keyboard.press('Enter')
                self.assertIn('两处相关', page.locator('#candidate-position-drill').inner_text())
                page.locator('#candidate-position-drill a').first.click()
                details = page.locator('[id^="candidate-facet-"]').first
                self.assertTrue(details.evaluate('(e)=>e.open'))
                self.assertIn('条件：若有记录', details.inner_text())
                details.get_by_role('link', name='查看本条完整原话与原分').click()
                self.assertTrue(page.locator('[id^="candidate-source-"]').evaluate('(e)=>e.open'))
                page.locator('#view-boiler').select_option('true')
                self.assertIn('没有候选位置', overlay.inner_text())
                self.assertIn('0/1', page.locator('#view-hits').text_content())
                page.locator('#view-boiler').select_option('*')
                output = os.environ.get('ATTENTION_CANDIDATE_EVIDENCE_DIR')
                for width in (1440, 420):
                    viewport = {'width': width, 'height': 1000}
                    if page.viewport_size != viewport:
                        # Resize redraws the graph synchronously; wait for its
                        # native event and next frame before resolving a node.
                        page.evaluate('''expected => {
                            window.__attentionResizeReady = new Promise((resolve, reject) => {
                                const timer = setTimeout(() => reject(new Error('Candidate resize did not complete')), 10000);
                                window.addEventListener('resize', () => requestAnimationFrame(() => {
                                    clearTimeout(timer);
                                    const graph = document.getElementById('candidate-position-overlay');
                                    if (innerWidth !== expected.width || innerHeight !== expected.height || !graph?.isConnected ||
                                        ['item:one', 'item:two'].some(id => graph.querySelectorAll('[data-candidate-region="' + id + '"]').length !== 1)) {
                                        reject(new Error('Candidate graph is incomplete after resize'));
                                        return;
                                    }
                                    resolve();
                                }), {once: true});
                            });
                        }''', viewport)
                        page.set_viewport_size(viewport)
                        page.evaluate('() => window.__attentionResizeReady')
                    overlay.scroll_into_view_if_needed()
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    if output:
                        Path(output).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(Path(output) / f'candidate-preview-{width}.png'))
                page.goto(preview_path.as_uri())
                page.get_by_role('link', name='查看分布图', exact=True).click()
                self.assertIn('未导入A', page.locator('#candidate-position-overlay').inner_text())
                saved = session.accept('engineering', actor='工程编辑', reason='核对')
                controller = Controller(); controller.open_attention(path)
                page.goto((path / 'attention.html').as_uri())
                open_panel(page, 'view-a-positions')
                open_panel(page, 'position-drill')
                saved_link = page.locator('#position-drill a').first
                saved_link.locator('xpath=ancestor::details[1]').locator(':scope > summary').click()
                saved_link.click()
                page.get_by_role('button', name='查看原话并修改').first.click()
                self.assertEqual(page.locator('#facet').input_value(), saved['opinions'][0]['facets'][0]['facet_id'])
                open_panel(page, 'editor-audit')
                page.locator('#actor').fill('工程编辑'); page.locator('#reason').fill('保留条件并纠正读法')
                page.locator('#interpretation').fill('如有记录才补充图例')
                page.locator('#stage').click()
                open_panel(page, 'editor-export')
                with page.expect_download() as download:
                    page.locator('#download').click()
                draft = Path(tmp) / 'draft.json'; download.value.save_as(draft)
                with closing(AttentionWorkspace(path)) as ws:
                    self.assertEqual(ws.apply(input_path=draft)['revision'], 2)
                self.assertEqual(controller.recover_attention()['revision'], 2)
                page.goto((path / 'attention.html').as_uri())
                open_panel(page, 'view-a-positions')
                open_panel(page, 'position-drill')
                saved_link = page.locator('#position-drill a').first
                saved_link.locator('xpath=ancestor::details[1]').locator(':scope > summary').click()
                saved_link.click()
                self.assertIn('如有记录才补充图例', page.locator('#view-detail').inner_text())
                self.assertEqual(errors, [])
                browser.close()
