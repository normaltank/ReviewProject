"""Native input checklist for repeatable, independent attention analyses."""
import copy
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from .attention_input import AttentionInput
from .core import require


VISIBILITY = {'普通意见（作者可见性未确认）': 'visibility_unknown', '明确作者可见': 'author_visible'}


class AttentionInputWindow:
    """The same controls are used for first entry, corrections and the next B batch."""

    def __init__(self, parent, controller, *, a_only=False, on_result=None, available=lambda: True):
        self.controller, self.on_result = controller, on_result
        self.available = available
        self.target_path = getattr(controller, 'attention_path', None) if a_only else None
        self.draft = AttentionInput()
        self.a_only = a_only
        self.window = tk.Toplevel(parent)
        self.window.title('录入A参照并显式换版' if a_only else '准备输入 · 建立独立关注分析')
        self.window.geometry('980x780')
        self.window.minsize(760, 640)
        self.status = tk.StringVar(value='逐条填写后加入清单。核对清单再建包；原件和旧包保持。')
        if a_only:
            self.status.set('显式导入的目标包：' + str(self.target_path) + '。核对完整A清单后导入；旧对应待核。')
        status_label = ttk.Label(self.window, textvariable=self.status, wraplength=920)
        status_label.pack(fill='x', padx=14, pady=10)
        status_label.bind('<Configure>', lambda event: status_label.configure(wraplength=max(200, event.width)))
        self.tabs = ttk.Notebook(self.window)
        self.tabs.pack(fill='both', expand=True, padx=14)
        if not a_only:
            self.b_tab = ttk.Frame(self.tabs, padding=10)
            self.tabs.add(self.b_tab, text='B原话与原分')
            self._b_controls()
        self.a_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.a_tab, text='A参照（可选）' if not a_only else '新的A版本')
        self._a_controls()
        self.review_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.review_tab, text='核对整份清单')
        self.preview = self._text(self.review_tab, height=20)
        self.preview.configure(state='disabled')
        self.tabs.bind('<<NotebookTabChanged>>', lambda event: self.refresh_review())
        actions = ttk.Frame(self.window, padding=14)
        actions.pack(side='bottom', fill='x')
        if a_only:
            self.import_a_button = ttk.Button(actions, text='将此A版本显式导入已打开包', command=lambda: self.guard(self.import_a))
            self.import_a_button.pack(side='left')
        else:
            self.build_button = ttk.Button(actions, text='核对并建立独立新包…', command=lambda: self.guard(self.build))
            self.build_button.pack(side='left')
        ttk.Button(actions, text='关闭输入准备', command=self.window.destroy).pack(side='right')
        footer = ttk.Label(self.window, text='B变化请从此清单另建独立包；已有观点不会迁移。输入文件随整个分析目录保存。', wraplength=920)
        footer.pack(side='bottom', fill='x', padx=14, pady=(0, 4))
        footer.bind('<Configure>', lambda event: footer.configure(wraplength=max(200, event.width)))
        # Pack the resizable notebook last so short windows retain their actions.
        self.tabs.pack_forget()
        self.tabs.pack(fill='both', expand=True, padx=14)
        self.refresh_review()

    def guard(self, action):
        from .desktop import safe_message
        try:
            require(self.available(), 'E_ATTENTION_BUSY')
            return action()
        except Exception as error:
            message = str(error)
            explanations = {
                'E_ATTENTION_TEXT': '请填写非空原话、锚点、定位或版本。原话和原分中的空格会保留。',
                'E_ATTENTION_A': '请核对A版本、条目及所属部分；部分非空时，每条A需选有效部分。',
                'E_ATTENTION_A_VERSION': 'A版本冲突或没有条目。修改内容需使用新的版本名；旧版保留。',
                'E_ATTENTION_PRIVATE': '只接收普通分区。私密意见不能加入此分析。',
                'E_ATTENTION_GROUP': '同一来源的普通分区需采用相同材料组声明，请更正清单。',
                'E_ATTENTION_UNSAVED_INPUT': '表单中还有未加入清单的内容，请先保存条目或清空表单。',
                'E_ATTENTION_SELECTION': '请先选择要修改或移除的清单项。',
                'E_ATTENTION_PART_IN_USE': '该部分仍被A条目使用，请先修改条目所属部分。',
                'E_ATTENTION_REVALIDATION': '来源已变化。旧包与快照保留；请重新选择普通来源，或还原原绑定。',
                'E_ATTENTION_TARGET': '已打开的包改变，请关闭此窗口并从目标包重新进入A换版。',
                'E_ATTENTION_BUSY': '本机入口正在处理另一项操作，请等待完成后再操作。',
            }
            self.status.set(message + '：' + explanations[message] if message in explanations else safe_message(error))
            if message == 'E_ATTENTION_OUTPUT_RECOVER':
                self.status.set(self.status.get() + ' 当前目标包：' + str(getattr(self.controller, 'attention_path', '')))
            return None

    @staticmethod
    def _entry(parent, label, variable, width=28):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=label, width=18).pack(side='left')
        widget = ttk.Entry(row, textvariable=variable, width=width)
        widget.pack(side='left', fill='x', expand=True)
        return widget

    @staticmethod
    def _text(parent, height=5):
        row = ttk.Frame(parent)
        row.pack(fill='both', expand=True)
        text = tk.Text(row, height=height, wrap='word', undo=True)
        scroll = ttk.Scrollbar(row, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        return text

    @staticmethod
    def _selected(box):
        selection = box.curselection()
        require(bool(selection), 'E_ATTENTION_SELECTION')
        return selection[0]

    def _b_controls(self):
        pane = ttk.Panedwindow(self.b_tab, orient='horizontal')
        pane.pack(fill='both', expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane, padding=(12, 0, 0, 0))
        pane.add(left, weight=1); pane.add(right, weight=3)
        ttk.Label(left, text='待建包的B清单').pack(anchor='w')
        self.b_list = tk.Listbox(left, exportselection=False, width=25)
        self.b_list.pack(fill='both', expand=True, pady=6)
        self.b_list.bind('<<ListboxSelect>>', lambda event: self.guard(self.load_b))
        ttk.Button(left, text='新建转录条目 / 清空表单', command=self.clear_b).pack(fill='x', pady=3)
        self.remove_b_button = ttk.Button(left, text='移除选中的清单项', command=lambda: self.guard(self.remove_b))
        self.remove_b_button.pack(fill='x', pady=3)
        self.workspace_button = ttk.Button(left, text='选择已导入工作区普通分区…', command=lambda: self.guard(self.choose_workspace))
        self.workspace_button.pack(fill='x', pady=3)
        self.anchor, self.locator, self.paper = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.visibility = tk.StringVar(value=next(iter(VISIBILITY)))
        self._entry(right, 'B锚点 / 记录名', self.anchor)
        self._entry(right, '原件定位说明', self.locator)
        self._entry(right, '材料组（可空）', self.paper)
        row = ttk.Frame(right); row.pack(fill='x', pady=3)
        ttk.Label(row, text='普通可见性', width=18).pack(side='left')
        ttk.Combobox(row, textvariable=self.visibility, values=list(VISIBILITY), state='readonly').pack(fill='x', expand=True)
        ttk.Label(right, text='逐字B原话（保留换行、空格及限定）').pack(anchor='w', pady=(8, 3))
        self.quote = self._text(right, height=5)
        ttk.Label(right, text='原分：零至任意项，标签和值逐字保留').pack(anchor='w', pady=(8, 3))
        self.score_label, self.score_value = tk.StringVar(), tk.StringVar()
        self._entry(right, '原分标签', self.score_label)
        self._entry(right, '原值（可空）', self.score_value)
        row = ttk.Frame(right); row.pack(fill='x')
        self.add_score_button = ttk.Button(row, text='原分加入 / 保存修改', command=self.save_score)
        self.add_score_button.pack(side='left', pady=3)
        ttk.Button(row, text='移除选中原分', command=lambda: self.guard(self.remove_score)).pack(side='left', padx=5)
        ttk.Button(row, text='清空原分表单', command=self.clear_score).pack(side='left')
        self.score_list = tk.Listbox(right, height=3, exportselection=False)
        self.score_list.pack(fill='x')
        self.score_list.bind('<<ListboxSelect>>', lambda event: self.load_score())
        self.save_b_button = ttk.Button(right, text='B条目加入 / 保存到清单', command=lambda: self.guard(self.save_b))
        self.save_b_button.pack(anchor='w', pady=8)
        self.scores = []
        self.editing_b = self.editing_score = None

    def clear_score(self):
        self.editing_score = None
        self.score_label.set(''); self.score_value.set('')
        self.score_list.selection_clear(0, 'end')

    def save_score(self):
        score = {'label': self.score_label.get(), 'raw_value': self.score_value.get()}
        if self.editing_score is None:
            self.scores.append(score)
        else:
            self.scores[self.editing_score] = score
        self.refresh_scores(); self.clear_score()

    def load_score(self):
        if self.score_list.curselection():
            self.editing_score = self.score_list.curselection()[0]
            score = self.scores[self.editing_score]
            self.score_label.set(score['label']); self.score_value.set(score['raw_value'])

    def refresh_scores(self):
        self.score_list.delete(0, 'end')
        for score in self.scores:
            self.score_list.insert('end', score['label'] + ' = ' + repr(score['raw_value']))

    def remove_score(self):
        del self.scores[self._selected(self.score_list)]
        self.refresh_scores(); self.clear_score()

    def clear_b(self):
        self.editing_b = None
        for field in (self.anchor, self.locator, self.paper): field.set('')
        self.visibility.set(next(iter(VISIBILITY)))
        self.quote.delete('1.0', 'end'); self.scores = []
        self.refresh_scores(); self.clear_score()
        self.b_list.selection_clear(0, 'end')

    def save_b(self):
        require(not self.score_label.get() and not self.score_value.get(), 'E_ATTENTION_UNSAVED_INPUT')
        values = (self.anchor.get(), self.quote.get('1.0', 'end-1c'), VISIBILITY[self.visibility.get()],
                  self.scores, self.locator.get(), self.paper.get())
        if self.editing_b is None:
            self.draft.add_transcription(*values)
        else:
            require(self.draft.records[self.editing_b]['kind'] == 'transcription', 'E_ATTENTION_SELECTION')
            self.draft.replace_transcription(self.editing_b, *values)
        self.clear_b(); self.refresh_b(); self.refresh_review()
        self.status.set('B条目已加入清单；可选中修改、移除或继续录入。')

    def refresh_b(self):
        self.b_list.delete(0, 'end')
        for record in self.draft.records:
            self.b_list.insert('end', record.get('anchor', record.get('section_id', '')) +
                               (' · 工作区' if record['kind'] == 'workspace' else ' · 转录'))

    def load_b(self):
        if not self.b_list.curselection(): return
        index = self._selected(self.b_list)
        self.clear_b()
        self.b_list.selection_set(index)
        record = self.draft.records[index]
        if record['kind'] == 'workspace':
            self.status.set('已选工作区分区；要更换来源或分组，请移除此项后重新选择。核对页可看原话和原分。')
            return
        self.editing_b = index
        self.anchor.set(record['anchor']); self.locator.set(record['locator']['description'])
        self.paper.set(record.get('paper_id', ''))
        self.visibility.set(next(label for label, value in VISIBILITY.items() if value == record['visibility']))
        self.quote.insert('1.0', record['text']); self.scores = copy.deepcopy(record['scores']); self.refresh_scores()

    def remove_b(self):
        self.draft.remove(self._selected(self.b_list))
        self.clear_b(); self.refresh_b(); self.refresh_review()

    def choose_workspace(self):
        path = filedialog.askdirectory(parent=self.window, title='选择已导入、含review.sqlite3的工作区')
        if not path: return
        sections = self.draft.workspace_options(path)
        selection = tk.Toplevel(self.window); selection.title('只选择普通分区')
        selection.geometry('700x480')
        ttk.Label(selection, text='仅列普通分区；原分与原定位一并保留，不带入私密区。', wraplength=660).pack(padx=12, pady=10)
        group = tk.StringVar()
        self._entry(selection, '材料组（可空）', group)
        box = tk.Listbox(selection, selectmode='extended', exportselection=False)
        box.pack(fill='both', expand=True, padx=12, pady=8)
        for section in sections:
            box.insert('end', section['section_id'] + ' · ' + section['label'] + ' · ' + section['text'][:65])
        def accept():
            require(bool(box.curselection()), 'E_ATTENTION_SELECTION')
            for index in box.curselection(): self.draft.add_workspace(path, sections[index]['section_id'], group.get())
            self.refresh_b(); self.refresh_review(); selection.destroy()
        ttk.Button(selection, text='将所选普通分区加入清单', command=lambda: self.guard(accept)).pack(pady=8)
        ttk.Button(selection, text='取消', command=selection.destroy).pack(pady=(0, 8))

    def _a_controls(self):
        self.version = tk.StringVar()
        self._entry(self.a_tab, 'A版本名', self.version)
        ttk.Label(self.a_tab, text='无A可留空。完整原话保留“可以、例如、必要时”等限定；身份编号自动生成。').pack(anchor='w', pady=4)
        pane = ttk.Panedwindow(self.a_tab, orient='horizontal'); pane.pack(fill='both', expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane, padding=(12, 0, 0, 0))
        pane.add(left, weight=1); pane.add(right, weight=3)
        ttk.Label(left, text='部分（可保留空部分）').pack(anchor='w')
        self.part_list = tk.Listbox(left, height=5, exportselection=False)
        self.part_list.pack(fill='x', pady=4)
        self.part_list.bind('<<ListboxSelect>>', lambda event: self.load_part())
        self.part_label = tk.StringVar()
        ttk.Entry(left, textvariable=self.part_label).pack(fill='x')
        self.save_part_button = ttk.Button(left, text='部分加入 / 保存修改', command=lambda: self.guard(self.save_part))
        self.save_part_button.pack(fill='x', pady=4)
        ttk.Button(left, text='清空部分表单', command=self.clear_part).pack(fill='x')
        ttk.Button(left, text='移除选中部分', command=lambda: self.guard(self.remove_part)).pack(fill='x', pady=4)
        ttk.Label(left, text='完整A条目').pack(anchor='w', pady=(12, 4))
        self.a_list = tk.Listbox(left, exportselection=False)
        self.a_list.pack(fill='both', expand=True)
        self.a_list.bind('<<ListboxSelect>>', lambda event: self.load_a())
        ttk.Button(left, text='新建A条目 / 清空表单', command=self.clear_a).pack(fill='x', pady=4)
        ttk.Button(left, text='移除选中A条目', command=lambda: self.guard(self.remove_a)).pack(fill='x')
        self.item_part, self.item_locator = tk.StringVar(), tk.StringVar()
        ttk.Label(right, text='所属部分（无部分时留空）').pack(anchor='w')
        self.part_box = ttk.Combobox(right, textvariable=self.item_part, state='readonly')
        self.part_box.pack(fill='x', pady=4)
        self._entry(right, 'A原件定位', self.item_locator)
        ttk.Label(right, text='完整A原话').pack(anchor='w', pady=(10, 4))
        self.a_text = self._text(right, height=9)
        self.save_a_button = ttk.Button(right, text='A条目加入 / 保存到清单', command=lambda: self.guard(self.save_a))
        self.save_a_button.pack(anchor='w', pady=8)
        self.actor, self.reason = tk.StringVar(), tk.StringVar()
        self._entry(right, '换版修改者声明', self.actor)
        self._entry(right, '显式换版理由', self.reason)
        ttk.Label(right, text='“显式导入”只改变已打开包的A。保留B、观点及旧A历史，旧对应待核。', wraplength=500).pack(anchor='w', pady=8)
        self.parts, self.items = [], []
        self.editing_part = self.editing_a = None

    def clear_part(self):
        self.part_label.set(''); self.editing_part = None
        self.part_list.selection_clear(0, 'end')

    def load_part(self):
        if self.part_list.curselection():
            self.editing_part = self._selected(self.part_list)
            self.part_label.set(self.parts[self.editing_part]['label'])

    def save_part(self):
        from .attention_input import nonempty
        label = nonempty(self.part_label.get())
        if self.editing_part is None: self.parts.append({'id': 'part-' + uuid.uuid4().hex, 'label': label})
        else: self.parts[self.editing_part]['label'] = label
        self.clear_part(); self.refresh_a_lists()

    def remove_part(self):
        index = self._selected(self.part_list)
        require(not any(i.get('part_id') == self.parts[index]['id'] for i in self.items), 'E_ATTENTION_PART_IN_USE')
        del self.parts[index]
        self.clear_part(); self.refresh_a_lists()

    def refresh_a_lists(self):
        self.part_list.delete(0, 'end'); self.a_list.delete(0, 'end')
        for part in self.parts: self.part_list.insert('end', part['label'])
        for item in self.items: self.a_list.insert('end', item['text'][:40])
        self.part_box['values'] = [str(n + 1) + ' · ' + p['label'] for n, p in enumerate(self.parts)]
        if self.item_part.get() not in self.part_box['values']: self.item_part.set('')
        self.refresh_review()

    def clear_a(self):
        self.editing_a = None; self.item_locator.set(''); self.item_part.set('')
        self.a_text.delete('1.0', 'end'); self.a_list.selection_clear(0, 'end')

    def load_a(self):
        if not self.a_list.curselection(): return
        self.editing_a = self._selected(self.a_list)
        item = self.items[self.editing_a]
        self.item_locator.set(item['locator']); self.a_text.delete('1.0', 'end'); self.a_text.insert('1.0', item['text'])
        self.item_part.set(next((str(n + 1) + ' · ' + p['label'] for n, p in enumerate(self.parts) if p['id'] == item.get('part_id')), ''))

    def save_a(self):
        from .attention_input import nonempty
        item = {'id': self.items[self.editing_a]['id'] if self.editing_a is not None else 'item-' + uuid.uuid4().hex,
                'text': nonempty(self.a_text.get('1.0', 'end-1c')), 'locator': nonempty(self.item_locator.get())}
        if self.parts:
            require(self.part_box.current() >= 0, 'E_ATTENTION_A')
            item['part_id'] = self.parts[self.part_box.current()]['id']
        if self.editing_a is None: self.items.append(item)
        else: self.items[self.editing_a] = item
        self.clear_a(); self.refresh_a_lists()
        self.status.set('完整A条目已加入清单；建包或显式导入前请核对版本及部分。')

    def remove_a(self):
        del self.items[self._selected(self.a_list)]
        self.clear_a(); self.refresh_a_lists()

    def reference(self):
        from .attention_input import nonempty
        return {'version': nonempty(self.version.get()) if self.items or self.parts or self.version.get() else 'no-a',
                'parts': copy.deepcopy(self.parts), 'items': copy.deepcopy(self.items)}

    def ensure_saved(self):
        require(not self.a_text.get('1.0', 'end-1c') and not self.item_locator.get() and not self.part_label.get(), 'E_ATTENTION_UNSAVED_INPUT')
        if not self.a_only:
            require(not any((self.anchor.get(), self.locator.get(), self.paper.get(), self.quote.get('1.0', 'end-1c'),
                             self.score_label.get(), self.score_value.get(), self.scores)), 'E_ATTENTION_UNSAVED_INPUT')

    def refresh_review(self):
        if not hasattr(self, 'preview'): return
        lines = ['待建包清单（未提交）', 'B来源选择数：' + str(len(self.draft.records))]
        for n, record in enumerate(self.draft.records):
            lines.append('\nB ' + str(n + 1) + ' · ' + record['kind'] + ' · 材料组：' + record.get('paper_id', '未声明'))
            if record['kind'] == 'workspace':
                lines.extend(['工作区：' + record['workspace'], '普通分区：' + record['section_id']])
                # The read-only adapter supplies only the selected ordinary text.
                try:
                    from .batch import source_state
                    state = source_state(record['workspace'])
                    require(self.draft.workspace_checks.get(record['workspace']) ==
                            (state['revision'], state['source']['source_id']), 'E_ATTENTION_REVALIDATION')
                    section = next(s for s in state['sections'] if s['section_id'] == record['section_id'])
                    require(section['visibility'] in {'author_visible', 'visibility_unknown'}, 'E_ATTENTION_PRIVATE')
                    lines.extend(['可见性：' + section['visibility'], '定位：' + str(section['locator']), section['text']])
                    scores = state['scores']
                except Exception:
                    lines.append('来源当前不可核验，请重新选择；建包前会拒收变化来源。'); scores = []
            else:
                lines.extend(['锚点：' + record['anchor'], '可见性：' + record['visibility'],
                              '定位：' + record['locator']['description'], record['text']])
                scores = record['scores']
            lines.append('原分：' + ('无' if not scores else ''))
            lines.extend(score['label'] + ' = ' + repr(score['raw_value']) for score in scores)
        lines.extend(['\nA版本：' + (self.version.get() or '未提供A'), '部分：' + str(len(self.parts)) + ' · 完整条目：' + str(len(self.items))])
        for part in self.parts:
            lines.append('部分：' + part['label'] + ('（空部分）' if not any(i.get('part_id') == part['id'] for i in self.items) else ''))
        for item in self.items:
            part = next((p['label'] for p in self.parts if p['id'] == item.get('part_id')), '未分组')
            lines.extend(['\nA · ' + part + ' · ' + item['locator'], item['text']])
        self.preview.configure(state='normal'); self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', '\n'.join(lines)); self.preview.configure(state='disabled')

    def build(self):
        self.ensure_saved(); self.draft.set_a(self.reference()); self.refresh_review()
        self.tabs.select(self.review_tab)
        parent = filedialog.askdirectory(parent=self.window, title='选择父目录（自动创建独立新子目录）')
        if not parent: return
        destination = Path(parent) / ('attention-' + uuid.uuid4().hex[:12])
        result = self.controller.build_prepared_attention(self.draft, destination)
        self.status.set('新包已建立，尚未整理观点：' + str(result['path']) + ' · 修订 ' + str(result['revision']) +
                        '。输入在 inputs/；可打开关注页整理，或修改此清单另建下一包。')
        if self.on_result: self.on_result(result)

    def import_a(self):
        require(self.target_path is not None and self.target_path == getattr(self.controller, 'attention_path', None), 'E_ATTENTION_TARGET')
        self.ensure_saved()
        result = self.controller.import_prepared_attention_a(self.reference(), self.actor.get(), self.reason.get())
        self.status.set('A版本已显式保存：' + str(result['path']) + ' · 修订 ' + str(result['revision']) + '；旧A历史保留，旧对应待核。')
        if self.on_result: self.on_result(result)
