"""Ordinary candidate workflow; replay is engineering verification only."""
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
    def doCleanups(self):
        result = super().doCleanups()
        # Collect destroyed Tcl objects on their owning main thread before a
        # later test starts any worker.
        import gc
        gc.collect()
        return result

    def test_source_or_a_changes_during_generation_make_result_unacceptable(self):
        import threading
        from reviewproto.attention_candidate_ui import CandidateSession
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

    def test_ordinary_desktop_button_opens_candidate_window_for_current_package(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pack'; prepare(path)
            script = '''import sys
import tkinter as tk
from unittest.mock import patch
from reviewproto import desktop
controller = desktop.Controller(); controller.open_attention(sys.argv[1])
original = tk.Tk
seen, errors = [], []
def create_root():
    root = original()
    root.report_callback_exception = lambda *args: errors.append(args)
    def inspect():
        try:
            def walk(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from walk(child)
            button = next(w for w in walk(root) if w.winfo_class() == 'TButton' and
                w.cget('text') == '生成并核对B内容与A位置候选')
            button.invoke(); root.update()
            seen.extend(w.title() for w in root.winfo_children() if isinstance(w, tk.Toplevel))
        finally: root.destroy()
    root.after(100, inspect)
    return root
with patch('tkinter.Tk', create_root), patch('reviewproto.desktop.Controller', return_value=controller):
    desktop.main()
assert seen == ['B内容与A位置候选'], seen
assert not errors, errors
'''
            result = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_service_ownership_keeps_launch_paths_and_stops_only_its_run(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from reviewproto.attention_candidate_ui import CandidateModelService
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
                command.return_value = SimpleNamespace(returncode=0, stdout=b'Started PID 123')
                service.start(resource, runtime)
                self.assertIn(str(resource), [str(v) for v in command.call_args.args[0]])
                self.assertIn(str(runtime), [str(v) for v in command.call_args.args[0]])
                service.stop()
                args = [str(v) for v in command.call_args.args[0]]
                self.assertEqual(args[-6:], ['-ResourceRoot', str(resource), '-RuntimeDir', str(runtime), '-ExpectedRunId', run_id])
                self.assertIsNone(service.owned)

    def test_frozen_target_generate_preview_accept_reopen(self):
        from reviewproto.attention_candidate_ui import CandidateSession
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
            self.assertIn('已在修订 1 接收', session.preview('engineering').read_text(encoding='utf-8'))
            reopened = CandidateSession(path)
            self.assertEqual(reopened.accept('engineering', actor='重复', reason='重放')['revision'], 1)
            with closing(AttentionWorkspace(path)) as ws:
                self.assertEqual(ws.state()['opinions'][0]['facets'][0]['status'], 'needs_review')

    def test_generation_uses_captured_identity_and_rejects_revision_change(self):
        from reviewproto.attention_candidate_ui import CandidateSession
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
        from reviewproto.attention_candidate_ui import CandidateSession, candidate_message
        from reviewproto.core import ReviewError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pack'; state, response = prepare(path)
            session = CandidateSession(path)
            empty = session.generate('empty', ReplayProvider([{'edits': [], 'themes': [], 'relations': []}]))
            self.assertEqual(empty['status'], 'zero_candidates')
            self.assertIn('零候选', session.preview('empty').read_text(encoding='utf-8'))
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

    def test_real_tk_generate_is_async_and_switch_does_not_accept_into_another_pack(self):
        import tkinter as tk
        import threading
        import time
        from reviewproto.attention_candidate_ui import AttentionCandidateWindow
        from reviewproto.desktop import Controller
        with tempfile.TemporaryDirectory() as tmp:
            path, other = Path(tmp) / 'one', Path(tmp) / 'two'
            state, response = prepare(path)
            prepare(other)
            started, finish = threading.Event(), threading.Event()
            threads = []
            class HeldReplay(ReplayProvider):
                def complete(self, request):
                    threads.append(threading.get_ident()); started.set()
                    if not finish.wait(10):
                        raise RuntimeError('engineering timeout')
                    return super().complete(request)
            root = tk.Tk(); root.withdraw()
            callback_errors = []
            root.report_callback_exception = lambda *args: callback_errors.append(args)
            self.addCleanup(root.destroy)
            controller = Controller(); controller.open_attention(path)
            window = AttentionCandidateWindow(root, controller,
                provider_factory=lambda **kwargs: HeldReplay([response]))
            self.addCleanup(lambda: window.window.destroy() if window.window.winfo_exists() else None)
            window.generate_button.invoke()
            self.assertTrue(started.wait(3))
            root.update()
            self.assertTrue(window.busy)
            self.assertNotEqual(threads[0], threading.get_ident())
            controller.open_attention(other)
            finish.set()
            deadline = time.monotonic() + 10
            while window.busy and time.monotonic() < deadline:
                root.update(); time.sleep(.02)
            self.assertFalse(window.busy, window.status.get())
            self.assertIn('工程回放', window.status.get())
            import os
            evidence = os.environ.get('ATTENTION_CANDIDATE_EVIDENCE_DIR')
            for width, height in ((920, 760), (760, 640)):
                window.window.geometry(f'{width}x{height}'); root.update()
                for button in (window.generate_button, window.preview_button, window.accept_button, window.open_button):
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), window.window.winfo_rootx() + width)
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), window.window.winfo_rooty() + height)
                if evidence:
                    from PIL import ImageGrab
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    for tab in range(3):
                        window.tabs.select(tab); root.update()
                        x, y = window.window.winfo_rootx(), window.window.winfo_rooty()
                        ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(str(Path(evidence) / f'tk-candidates-{tab}-{width}.png'))
            window.actor.set('editor'); window.reason.set('inspect')
            window.accept_button.invoke(); root.update()
            self.assertIn('目标已切换', window.status.get())
            for target in (path, other):
                with closing(AttentionWorkspace(target)) as ws:
                    self.assertEqual(ws.state()['revision'], 0)
            controller.open_attention(path)
            window.accept_button.invoke()
            deadline = time.monotonic() + 10
            while window.busy and time.monotonic() < deadline:
                root.update(); time.sleep(.02)
            self.assertIn('已接收为待核', window.status.get())
            with closing(AttentionWorkspace(path)) as ws:
                self.assertEqual(ws.state()['revision'], 1)
            self.assertEqual(callback_errors, [])

    def test_chrome_preview_regions_evidence_and_accept_edit_apply_reopen(self):
        import copy
        import os
        from playwright.sync_api import sync_playwright
        from reviewproto.attention_candidate_ui import CandidateSession
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
                overlay = page.locator('#candidate-position-overlay')
                self.assertIn('未接收、全部待核', overlay.inner_text())
                self.assertEqual(overlay.locator('[data-candidate-region="item:one"]').count(), 1)
                self.assertEqual(overlay.locator('[data-candidate-region="item:two"]').count(), 1)
                self.assertIn('1/1', overlay.inner_text())
                self.assertIn('0/1', page.locator('#view-hits').inner_text())
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
                self.assertIn('0/1', page.locator('#view-hits').inner_text())
                page.locator('#view-boiler').select_option('*')
                output = os.environ.get('ATTENTION_CANDIDATE_EVIDENCE_DIR')
                for width in (1440, 420):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    overlay.scroll_into_view_if_needed()
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    if output:
                        Path(output).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(Path(output) / f'candidate-preview-{width}.png'))
                page.goto(preview_path.as_uri())
                self.assertIn('未导入A', page.locator('#candidate-position-overlay').inner_text())
                saved = session.accept('engineering', actor='工程编辑', reason='核对')
                controller = Controller(); controller.open_attention(path)
                page.goto((path / 'attention.html').as_uri())
                page.locator('#position-drill a').first.click()
                page.get_by_role('button', name='在原话与编辑区核对').first.click()
                self.assertEqual(page.locator('#facet').input_value(), saved['opinions'][0]['facets'][0]['facet_id'])
                page.locator('#actor').fill('工程编辑'); page.locator('#reason').fill('保留条件并纠正读法')
                page.locator('#interpretation').fill('如有记录才补充图例')
                page.locator('#stage').click()
                with page.expect_download() as download:
                    page.locator('#download').click()
                draft = Path(tmp) / 'draft.json'; download.value.save_as(draft)
                self.assertEqual(controller.apply_attention(draft)['revision'], 2)
                self.assertEqual(controller.recover_attention()['revision'], 2)
                page.goto((path / 'attention.html').as_uri())
                page.locator('#position-drill a').first.click()
                self.assertIn('如有记录才补充图例', page.locator('#view-detail').inner_text())
                self.assertEqual(errors, [])
                browser.close()
