"""Real Tk controls, with only native file dialogs replaced at the OS boundary."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class AttentionInputTk(unittest.TestCase):
    def test_a_target_stays_visible_after_saving_reviewing_and_current_package_changes(self):
        import tkinter as tk
        from reviewproto.attention_input_ui import AttentionInputWindow
        from reviewproto.desktop import Controller

        root = tk.Tk(); self.addCleanup(root.destroy)
        root.withdraw()
        controller = Controller()
        entry = AttentionInputWindow(root, controller)
        entry.anchor.set('合成B'); entry.locator.set('合成定位')
        entry.quote.insert('1.0', '保留原始材料。'); entry.save_b_button.invoke()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / ('synthetic-target-' * 5)
            parent.mkdir()
            with patch('tkinter.filedialog.askdirectory', return_value=str(parent)):
                entry.build_button.invoke()
            target = controller.attention_path
            self.assertIsNotNone(target, entry.status.get())
            entry.window.withdraw()
            windows = []
            for width, height in ((980, 780), (760, 640)):
                window = AttentionInputWindow(root, controller, a_only=True)
                windows.append(window)
                window.window.geometry(f'{width}x{height}')
                window.version.set('合成新A')
                for number in range(16):
                    window.item_locator.set('合成A第' + str(number) + '项')
                    window.a_text.insert('1.0', '可以保留完整条件与范围。' + str(number))
                    window.save_a_button.invoke()
                window.tabs.select(window.review_tab)
                root.update()
                with self.subTest(size=(width, height), stage='saved-review'):
                    self.assert_target_visible(window, target)
                    self.assertTrue(window.import_a_button.winfo_ismapped())
                    self.assertLessEqual(window.import_a_button.winfo_rooty() + window.import_a_button.winfo_height(),
                                         window.window.winfo_rooty() + height)
                    self.assertLess(window.preview.yview()[1], 1.0)
                    window.preview.yview_moveto(1)
                    root.update()
                    self.assertEqual(window.preview.yview()[1], 1.0)
                window.window.withdraw()
            with patch('tkinter.filedialog.askdirectory', return_value=tmp):
                entry.build_button.invoke()
            self.assertNotEqual(controller.attention_path, target)
            for window in windows:
                window.window.deiconify(); root.update()
                window.import_a_button.invoke(); root.update()
                self.assertIn('E_ATTENTION_TARGET', window.status.get())
                self.assertEqual(window.target_path, target)
                self.assert_target_visible(window, target)
                window.window.withdraw()

    def assert_target_visible(self, window, target):
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        labels = [widget for widget in descendants(window.window)
                  if widget.winfo_class() == 'TLabel' and widget.winfo_ismapped()
                  and str(target) in str(widget.cget('text'))]
        self.assertTrue(labels, 'The frozen destination must remain visible after status messages change')
        for label in labels:
            self.assertGreaterEqual(label.winfo_height(), label.winfo_reqheight())
            self.assertGreaterEqual(label.winfo_rooty(), window.window.winfo_rooty())
            self.assertLessEqual(label.winfo_rooty() + label.winfo_height(),
                                 window.window.winfo_rooty() + window.window.winfo_height())

    def test_workspace_picker_lists_only_ordinary_sections_and_builds_the_selection(self):
        import json
        import tkinter as tk
        from contextlib import closing
        from reviewproto.attention_input_ui import AttentionInputWindow
        from reviewproto.desktop import Controller
        from reviewproto.store import Workspace
        from reviewproto.attention import AttentionWorkspace
        root = tk.Tk(); self.addCleanup(root.destroy)
        controller = Controller()
        window = AttentionInputWindow(root, controller)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp); source = path / 'source.json'
            source.write_text(json.dumps({'scores': [], 'sections': [
                {'section_id': 'ordinary', 'label': '评审意见', 'text': '普通原话😀'},
                {'section_id': 'private', 'label': '其他意见（作者不可见）', 'text': 'PRIVATE_NEVER_COPY'}]}), encoding='utf-8')
            with closing(Workspace(path / 'source')) as ws: ws.run(source, 'synthetic', 'json')
            with patch('tkinter.filedialog.askdirectory', return_value=str(path / 'source')):
                window.workspace_button.invoke()
            root.update()
            picker = next(w for w in window.window.winfo_children() if isinstance(w, tk.Toplevel))
            box = next(w for w in picker.winfo_children() if isinstance(w, tk.Listbox))
            self.assertEqual(box.size(), 1)
            self.assertNotIn('PRIVATE_NEVER_COPY', str(box.get(0, 'end')))
            box.selection_set(0)
            button = next(w for w in picker.winfo_children() if w.winfo_class() == 'TButton' and
                          w.cget('text') == '将所选普通分区加入清单')
            button.invoke()
            with patch('tkinter.filedialog.askdirectory', return_value=tmp): window.build_button.invoke()
            with closing(AttentionWorkspace(controller.attention_path)) as ws:
                state = ws.state()
                self.assertEqual(state['records'][0]['text'], '普通原话😀')
                self.assertNotIn('PRIVATE_NEVER_COPY', json.dumps(state))

    def test_real_desktop_entry_opens_ordinary_input_window(self):
        import tkinter as tk
        from reviewproto import desktop
        from reviewproto.attention_input_ui import AttentionInputWindow
        original = tk.Tk
        observations = []
        input_windows = []
        def open_input(*args, **kwargs):
            window = AttentionInputWindow(*args, **kwargs)
            input_windows.append(window)
            return window
        def create_root():
            root = original()
            def inspect():
                try:
                    def descendants(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from descendants(child)
                    visible = [w for w in descendants(root) if w.winfo_class() == 'TButton' and w.winfo_ismapped()]
                    self.assertEqual({w.cget('text') for w in visible}, {'新建分析', '打开已有分析'})
                    button = next(w for w in visible if w.cget('text') == '新建分析')
                    button.invoke(); root.update()
                    titles = [w.title() for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
                    self.assertIn('新建分析 · 输入材料', titles)
                    entry = input_windows[-1]
                    entry.quote.insert('1.0', '合成评语。')
                    entry.save_b_button.invoke()
                    with tempfile.TemporaryDirectory() as tmp:
                        with patch('tkinter.filedialog.askdirectory', return_value=tmp):
                            entry.build_button.invoke()
                        root.update()
                        visible = [w for w in descendants(root) if w.winfo_class() == 'TButton' and w.winfo_ismapped()]
                        self.assertTrue(any(w.cget('text') == '分析评语' for w in visible), entry.status.get())
                        self.assertTrue(any(w.cget('text') == '查看并修改结果' for w in visible))
                        self.assertFalse(any(w.cget('text') == '显式启动本项目已安装模型' for w in visible))
                        change_a = next(w for w in visible if w.cget('text') == '修改A参照（可选）')
                        change_a.invoke(); root.update()
                        self.assertTrue(input_windows[-1].a_only)
                        self.assertFalse(any(w.winfo_class() == 'TButton' and
                            w.cget('text') == '保存下载的修改并查看' for w in descendants(root)))
                    observations.append(True)
                finally:
                    for callback in root.tk.call('after', 'info'):
                        root.after_cancel(callback)
                    root.destroy()
            root.after(100, inspect)
            return root
        with patch('tkinter.Tk', create_root), \
             patch('reviewproto.attention_input_ui.AttentionInputWindow', side_effect=open_input):
            desktop.main()
        self.assertEqual(observations, [True])

    def test_pasted_material_builds_without_inventing_original_file_locations(self):
        import tkinter as tk
        from contextlib import closing
        from reviewproto.attention_input_ui import AttentionInputWindow
        from reviewproto.desktop import Controller
        from reviewproto.attention import AttentionWorkspace
        root = tk.Tk(); self.addCleanup(root.destroy)
        controller = Controller()
        window = AttentionInputWindow(root, controller)
        quote = ' 原话😀\n若能补充，可以说明。 '
        window.quote.insert('1.0', quote)
        window.save_b_button.invoke()
        window.version.set('手工清单1')
        window.a_text.insert('1.0', '必要时说明范围。')
        window.save_a_button.invoke()
        with tempfile.TemporaryDirectory() as tmp:
            with patch('tkinter.filedialog.askdirectory', return_value=tmp):
                window.build_button.invoke()
            self.assertIsNotNone(getattr(controller, 'attention_path', None), window.status.get())
            with closing(AttentionWorkspace(controller.attention_path)) as ws:
                state = ws.state()
                self.assertEqual(state['records'][0]['text'], quote)
                self.assertIn('未提供原件位置', str(state['records'][0]['locator']))
                self.assertEqual(state['a_reference']['items'][0]['text'], '必要时说明范围。')
                self.assertIn('未提供原件位置', state['a_reference']['items'][0]['locator'])

    def test_a_entry_empty_part_replacement_and_changed_b_make_independent_packages(self):
        import tkinter as tk
        from reviewproto.attention_input_ui import AttentionInputWindow
        from reviewproto.desktop import Controller
        from reviewproto.attention import AttentionWorkspace
        from contextlib import closing
        root = tk.Tk(); self.addCleanup(root.destroy)
        controller = Controller()
        window = AttentionInputWindow(root, controller)
        for number in range(3):
            window.anchor.set('合成B' + str(number)); window.locator.set('第' + str(number) + '页')
            window.paper.set('材料组甲' if number < 2 else '材料组乙')
            window.quote.insert('1.0', '合成原话😀' + str(number))
            for score in range(number):
                window.score_label.set('自由分' + str(score)); window.score_value.set(' 原值 ')
                window.add_score_button.invoke()
            window.save_b_button.invoke()
        window.version.set('Tk参照甲')
        for label in ('第一部分', '第二部分', '空部分'):
            window.part_label.set(label); window.save_part_button.invoke()
        for number in range(3):
            window.part_box.current(0 if number == 0 else 1)
            window.item_locator.set('A第' + str(number) + '项')
            window.a_text.insert('1.0', '可以例如说明😀\n完整条件' + str(number))
            window.save_a_button.invoke()
        root.update()
        with tempfile.TemporaryDirectory() as tmp:
            with patch('tkinter.filedialog.askdirectory', return_value=tmp): window.build_button.invoke()
            first = controller.attention_path
            with closing(AttentionWorkspace(first)) as ws:
                before = ws.state()
                self.assertEqual(len(before['records']), 3)
                self.assertEqual(len(before['a_reference']['parts']), 3)
                self.assertEqual(len(before['a_reference']['items']), 3)
                self.assertIn('完整条件', before['a_reference']['items'][0]['text'])
                self.assertEqual(before['records'][1]['scores'][0]['raw_value'], ' 原值 ')
            a_window = AttentionInputWindow(root, controller, a_only=True)
            a_window.version.set('Tk参照乙'); a_window.item_locator.set('新A第1项')
            a_window.a_text.insert('1.0', '往往关注新的内容。'); a_window.save_a_button.invoke()
            a_window.actor.set('合成编辑'); a_window.reason.set('显式换版')
            a_window.import_a_button.invoke()
            with closing(AttentionWorkspace(first)) as ws:
                changed_a = ws.state()
                self.assertEqual(changed_a['a_reference']['version'], 'Tk参照乙')
                self.assertEqual(changed_a['records'], before['records'])
                self.assertEqual(changed_a['analysis_id'], before['analysis_id'])
            saved = {p.name: p.read_bytes() for p in first.iterdir() if p.is_file()}
            window.b_list.selection_set(0); window.load_b()
            window.quote.delete('1.0', 'end'); window.quote.insert('1.0', '更正后的B原话😀')
            window.save_b_button.invoke()
            with patch('tkinter.filedialog.askdirectory', return_value=tmp): window.build_button.invoke()
            self.assertNotEqual(controller.attention_path, first)
            self.assertEqual({p.name: p.read_bytes() for p in first.iterdir() if p.is_file()}, saved)
            a_window.version.set('不得误入新B包')
            a_window.import_a_button.invoke()
            self.assertIn('E_ATTENTION_TARGET', a_window.status.get())

    def test_ordinary_b_controls_build_and_cancel_keep_open_analysis(self):
        import tkinter as tk
        from reviewproto.attention_input_ui import AttentionInputWindow
        from reviewproto.desktop import Controller
        from reviewproto.attention import AttentionWorkspace
        from contextlib import closing
        root = tk.Tk()
        self.addCleanup(root.destroy)
        controller = Controller()
        window = AttentionInputWindow(root, controller)
        root.update()
        window.anchor.set('Tk甲😀')
        window.locator.set('合成第1页')
        window.quote.insert('1.0', ' 清晰😀。清晰😀。\n保留空格 ')
        window.score_label.set('自由标签α')
        window.score_value.set(' 4 / 甲 ')
        window.add_score_button.invoke()
        window.save_b_button.invoke()
        self.assertEqual(len(window.draft.records), 1)
        window.anchor.set('Tk乙')
        window.locator.set('合成第2页')
        window.quote.insert('1.0', '建议解释条件。')
        window.save_b_button.invoke()
        with tempfile.TemporaryDirectory() as tmp:
            with patch('tkinter.filedialog.askdirectory', return_value=tmp):
                window.build_button.invoke()
            root.update()
            path = controller.attention_path
            with closing(AttentionWorkspace(path)) as ws:
                state = ws.state()
                self.assertEqual(len(state['records']), 2)
                self.assertEqual(state['records'][0]['scores'][0]['raw_value'], ' 4 / 甲 ')
            self.assertIn('尚未整理观点', window.status.get())
            self.assertEqual(len(window.draft.records), 2)
            with patch('tkinter.filedialog.askdirectory', return_value=''):
                window.build_button.invoke()
            self.assertEqual(controller.attention_path, path)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)
