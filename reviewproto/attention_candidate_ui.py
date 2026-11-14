"""Ordinary, target-bound local candidate workflow. No SQLite crosses threads."""
from contextlib import closing
from pathlib import Path
import copy
import json
import os
import queue
import re
import threading
import uuid

from .attention import AttentionWorkspace
from .attention_candidates import generate, preview, accept, LocalProvider
from .attention_candidate_render import render_candidate_preview
from .core import require


class CandidateSession:
    def __init__(self, path):
        self.path = Path(path).absolute()
        require((self.path / 'attention.sqlite3').is_file(), 'E_ATTENTION_EMPTY')
        with closing(AttentionWorkspace(self.path)) as ws:
            self.snapshot = copy.deepcopy(ws.state())

    def generate(self, run_id, provider, record_ids=None, context_chars=24000):
        # Called on worker: create, use and close its connection on this thread.
        with closing(AttentionWorkspace(self.path)) as ws:
            current = ws.state()
            require(current['analysis_id'] == self.snapshot['analysis_id'] and
                    current['revision'] == self.snapshot['revision'] and
                    current['input_fingerprint'] == self.snapshot['input_fingerprint'],
                    'E_ATTENTION_TARGET')
            return generate(ws, run_id, provider, record_ids, context_chars)

    def preview(self, run_id):
        with closing(AttentionWorkspace(self.path)) as ws:
            run = preview(ws, run_id)
            current = ws.state()
            if current['material_status'] != 'current':
                run['validity'] = 'needs_revalidation'
            from .batch import read_json, checked_local
            from .store import encoded
            from .core import digest
            receipt = checked_local(self.path / 'candidate-runs' / run_id / 'acceptance.json')
            if receipt.is_file():
                fingerprint = digest(encoded(read_json(receipt)))
                applied = next((h for h in current['history'] if h['fingerprint'] == fingerprint), None)
                run['accepted_revision'] = applied['revision'] if applied else None
        target = self.path / 'candidate-runs' / run_id / 'preview.html'
        from .store import atomic
        atomic(target, render_candidate_preview(run).encode('utf-8'))
        return target

    def accept(self, run_id, *, actor, reason):
        with closing(AttentionWorkspace(self.path)) as ws:
            require(ws.state()['analysis_id'] == self.snapshot['analysis_id'], 'E_ATTENTION_TARGET')
            return accept(ws, run_id, actor=actor, reason=reason)

    def runs(self):
        # Only actual candidate run directories are offered, never caller paths.
        root = self.path / 'candidate-runs'
        return sorted(p.parent.name for p in root.glob('*/run.json') if p.is_file())


def candidate_message(error):
    code = str(error)
    if code == 'E_ATTENTION_TARGET':
        return '目标或保存修订已变化。请关闭候选窗口，从当前分析包重新打开；原候选仍保留在原包。'
    if code == 'E_ATTENTION_REVALIDATION':
        return '来源、A或保存修订已变化，候选不能接收。请恢复关注页核对，并重新生成；旧记录保留。'
    if code == 'E_ATTENTION_OUTPUT_RECOVER':
        return '修改可能已经保存，但页面输出未完成。请点击恢复并重开，再核对修订；同一候选可安全重复接收。'
    if code in {'E_ATTENTION_ENDPOINT', 'E_ATTENTION_MODEL', 'E_ATTENTION_CAPACITY'}:
        return '本机模型设置无效。请核对回环地址、模型名称、输出长度和上下文上限。'
    if code == 'E_ATTENTION_NO_CANDIDATES':
        return '本次没有可接收候选。请查看预览中的未完成范围，调整选择后重新生成或人工补录。'
    if code.startswith('E_LOCAL_MODEL') or code == 'E_MODEL_NOT_OWNED':
        return '模型服务操作未完成。请核对已安装资源与独立运行目录，并检查端口是否已使用；不会接管其他进程。'
    return '操作未完成。请保留候选记录，恢复并重开关注页核对保存状态后重试。'


class CandidateModelService:
    """Separate ownership from the legacy extractor and from any existing port."""
    def __init__(self):
        self.owned = None

    def start(self, resource, runtime):
        from .desktop import ROOT, run_powershell
        require(self.owned is None, 'E_LOCAL_MODEL_OWNED')
        resource, runtime = Path(resource).resolve(), Path(runtime).absolute()
        result = run_powershell(['-ExecutionPolicy', 'Bypass', '-File', ROOT / 'scripts/start-local-model.ps1',
                                 '-ResourceRoot', resource, '-RuntimeDir', runtime])
        require(result.returncode == 0, 'E_LOCAL_MODEL_START')
        state = json.loads((runtime / 'server-state.json').read_text(encoding='utf-8-sig'))
        output = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else result.stdout
        match = re.search(r'PID (\d+)', output or '')
        require(match is not None and state.get('pid') == int(match[1]) and
                Path(state.get('repo_root', '')).absolute() == ROOT and
                re.fullmatch('[0-9a-f]{32}', state.get('run_id', '')) is not None and
                state.get('owner') == 'ReviewProject/scripts/local-model/v1', 'E_MODEL_NOT_OWNED')
        self.owned = (resource, runtime, state['run_id'])

    def stop(self):
        from .desktop import ROOT, run_powershell
        require(self.owned is not None, 'E_MODEL_NOT_OWNED')
        resource, runtime, run_id = self.owned
        result = run_powershell(['-ExecutionPolicy', 'Bypass', '-File', ROOT / 'scripts/stop-local-model.ps1',
                                 '-ResourceRoot', resource, '-RuntimeDir', runtime, '-ExpectedRunId', run_id])
        require(result.returncode == 0, 'E_LOCAL_MODEL_STOP')
        self.owned = None


class AttentionCandidateWindow:
    """Tk owns controls; workers receive only captured values and frozen targets."""
    def __init__(self, parent, controller, *, provider_factory=LocalProvider, on_result=None):
        import tkinter as tk
        from tkinter import ttk
        from .desktop import ROOT
        self.controller, self.provider_factory, self.on_result = controller, provider_factory, on_result
        self.session = CandidateSession(controller.attention_path)
        self.target_path = self.session.path
        self.service = CandidateModelService()
        self.results, self.busy, self.run_id = queue.Queue(), False, None
        self.window = tk.Toplevel(parent)
        self.window.title('B内容与A位置候选')
        self.window.geometry('920x760'); self.window.minsize(640, 620)
        self.status = tk.StringVar(value='选择记录并生成。候选先理解B，再独立对照A；生成不会保存正式分析。')
        self.actor, self.reason = tk.StringVar(), tk.StringVar()
        self.endpoint = tk.StringVar(value='http://127.0.0.1:8766/v1')
        self.model = tk.StringVar(value='reviewproject-qwen3-4b-q4km')
        self.context_chars, self.max_tokens = tk.StringVar(value='24000'), tk.StringVar(value='4096')
        self.resource = tk.StringVar(value=str(ROOT))
        self.runtime = tk.StringVar(value=str(ROOT / 'work' / ('local-model-candidates-' + uuid.uuid4().hex[:12])))
        target_label = ttk.Label(self.window, text='固定目标：' + str(self.target_path), wraplength=850)
        target_label.pack(fill='x', padx=14, pady=10)
        target_label.bind('<Configure>', lambda e: target_label.configure(wraplength=max(200, e.width)))
        footer = ttk.Frame(self.window, padding=14); footer.pack(side='bottom', fill='x')
        message = ttk.Label(footer, textvariable=self.status, wraplength=850)
        message.pack(fill='x', pady=(0, 8)); message.bind('<Configure>', lambda e: message.configure(wraplength=max(200, e.width)))
        self.tabs = ttk.Notebook(self.window); self.tabs.pack(fill='both', expand=True, padx=14)
        records = ttk.Frame(self.tabs, padding=10); self.tabs.add(records, text='记录范围')
        self.record_list = tk.Listbox(records, selectmode='extended', exportselection=False, height=10)
        scrollbar = ttk.Scrollbar(records, command=self.record_list.yview)
        self.record_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y'); self.record_list.pack(fill='both', expand=True)
        self.record_ids = [r['record_id'] for r in self.session.snapshot['records']]
        for r in self.session.snapshot['records']:
            self.record_list.insert('end', r['anchor'] + ' · ' + str(len(r['sections'])) + ' 个完整分区 · ' + r['text'][:55])
        self.record_list.selection_set(0, 'end')
        model_container = ttk.Frame(self.tabs); self.tabs.add(model_container, text='本机模型设置')
        canvas = tk.Canvas(model_container, highlightthickness=0)
        model_scroll = ttk.Scrollbar(model_container, command=canvas.yview)
        canvas.configure(yscrollcommand=model_scroll.set)
        model_scroll.pack(side='right', fill='y'); canvas.pack(fill='both', expand=True)
        model_tab = ttk.Frame(canvas, padding=10)
        model_body = canvas.create_window((0, 0), window=model_tab, anchor='nw')
        model_tab.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(model_body, width=e.width))
        model_note = ttk.Label(model_tab, text='可使用已由你启动的回环模型。仅下方“启动”创建的实例可由本窗口停止。', wraplength=750)
        model_note.pack(fill='x', pady=5)
        model_note.bind('<Configure>', lambda e: model_note.configure(wraplength=max(200, e.width)))
        def entry(parent, label, variable):
            ttk.Label(parent, text=label).pack(anchor='w')
            e = ttk.Entry(parent, textvariable=variable); e.pack(fill='x', pady=(0, 6)); return e
        entry(model_tab, '回环模型地址', self.endpoint)
        entry(model_tab, '模型名称', self.model)
        row = ttk.Frame(model_tab); row.pack(fill='x')
        for label, value in [('输入字符上限（整段超限会明确列出）', self.context_chars), ('最大输出长度', self.max_tokens)]:
            col = ttk.Frame(row); col.pack(side='left', fill='x', expand=True, padx=(0, 10)); entry(col, label, value)
        entry(model_tab, '已安装资源根目录（含 .tools/local-llm）', self.resource)
        from tkinter import filedialog
        def choose_resource():
            path = filedialog.askdirectory(parent=self.window, title='选择已有模型资源根目录')
            if path: self.resource.set(path)
        ttk.Button(model_tab, text='选择已安装资源目录', command=choose_resource).pack(anchor='w')
        entry(model_tab, '本次独立运行目录（新的空目录）', self.runtime)
        def choose_runtime():
            path = filedialog.askdirectory(parent=self.window, title='选择父目录，将建立独立运行子目录')
            if path: self.runtime.set(str(Path(path) / ('local-model-' + uuid.uuid4().hex[:12])))
        ttk.Button(model_tab, text='选择运行目录的父目录', command=choose_runtime).pack(anchor='w')
        service_row = ttk.Frame(model_tab); service_row.pack(fill='x', pady=8)
        self.start_button = ttk.Button(service_row, text='启动已安装模型', command=self.start_service); self.start_button.pack(side='left')
        self.stop_button = ttk.Button(service_row, text='停止本窗口启动的模型', command=self.stop_service); self.stop_button.pack(side='left', padx=8)
        history = ttk.Frame(self.tabs, padding=10); self.tabs.add(history, text='候选历史与接收')
        ttk.Label(history, text='接收只新增待核分析；之后在普通关注页核对、纠正并应用草稿。', wraplength=750).pack(anchor='w', pady=8)
        self.history = ttk.Combobox(history, state='readonly', values=self.session.runs()); self.history.pack(fill='x', pady=8)
        self.history.bind('<<ComboboxSelected>>', lambda e: self.select_run())
        entry(history, '修改者声明', self.actor); entry(history, '接收理由', self.reason)
        self.generate_button = ttk.Button(footer, text='生成所选记录候选', command=self.generate); self.generate_button.pack(side='left')
        self.preview_button = ttk.Button(footer, text='预览候选与位置', command=self.open_preview); self.preview_button.pack(side='left', padx=6)
        self.accept_button = ttk.Button(footer, text='显式接收为待核', command=self.accept); self.accept_button.pack(side='left')
        self.open_button = ttk.Button(footer, text='恢复并重开关注页', command=self.open_saved); self.open_button.pack(side='right')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self._controls(); self.timer = self.window.after(80, self.poll)
        self.window.bind('<Destroy>', self._destroyed, add='+')

    def _controls(self):
        for b in (self.generate_button, self.open_button, self.start_button):
            b.configure(state='disabled' if self.busy else 'normal')
        for b in (self.preview_button, self.accept_button):
            b.configure(state='normal' if self.run_id and not self.busy else 'disabled')
        self.stop_button.configure(state='normal' if self.service.owned and not self.busy else 'disabled')
        self.history.configure(state='disabled' if self.busy else 'readonly')

    def _target_current(self):
        current = getattr(self.controller, 'attention_path', None)
        if current is None or Path(current).absolute() != self.target_path:
            self.status.set('目标已切换。请先在本机入口重新打开上方固定分析包，或关闭本窗口后为新包重新打开候选窗口。')
            return False
        return True

    def submit(self, action, worker):
        if self.busy: return
        self.busy = True; self._controls()
        self.status.set('正在处理，请稍候。窗口仍可查看；结果只属于上方固定目标。')
        results = self.results
        def execute():
            try: results.put((action, worker(), None))
            except Exception as exc: results.put((action, None, exc))
        threading.Thread(target=execute, daemon=True).start()

    def generate(self):
        if self.busy or not self._target_current(): return
        ids = [self.record_ids[i] for i in self.record_list.curselection()]
        if not ids:
            self.status.set('请至少选择一条评语记录。每条所选记录的全部普通分区均会处理。'); return
        try:
            chars, tokens = int(self.context_chars.get()), int(self.max_tokens.get())
            provider = self.provider_factory(endpoint=self.endpoint.get(), model=self.model.get(), max_tokens=tokens)
        except Exception:
            self.status.set('请核对本机模型设置；输入和输出上限须为有效整数，地址须为本机回环。'); return
        run_id = 'desktop-' + uuid.uuid4().hex
        session = self.session
        self.submit('generate', lambda: session.generate(run_id, provider, ids, chars))

    def select_run(self):
        self.run_id = self.history.get() or None; self._controls()
        self.status.set('已选择候选历史。请预览并核对绑定；旧修订候选不能首次接收。')

    def open_preview(self):
        run_id, session = self.run_id, self.session
        if run_id: self.submit('preview', lambda: session.preview(run_id))

    def accept(self):
        if self.busy or not self.run_id or not self._target_current(): return
        actor, reason, run_id = self.actor.get(), self.reason.get(), self.run_id
        if not actor.strip() or not reason.strip():
            self.tabs.select(2); self.status.set('请填写修改者声明与接收理由，再显式接收为待核。'); return
        session = self.session
        self.submit('accept', lambda: session.accept(run_id, actor=actor, reason=reason))

    def open_saved(self):
        if not self._target_current(): return
        path = self.target_path
        def recover():
            with closing(AttentionWorkspace(path)) as ws: return ws.recover()
        self.submit('saved', recover)

    def start_service(self):
        resource, runtime, service = self.resource.get(), self.runtime.get(), self.service
        self.submit('start', lambda: service.start(resource, runtime))

    def stop_service(self):
        self.submit('stop', self.service.stop)

    def poll(self):
        try:
            while True:
                action, result, error = self.results.get_nowait()
                self.busy = False
                if error:
                    self.status.set(candidate_message(error))
                elif action == 'generate':
                    self.run_id = result['run_id']; self.history.configure(values=self.session.runs()); self.history.set(self.run_id)
                    statuses = {'complete': '处理完成', 'partial': '部分处理', 'failed': '处理失败', 'zero_candidates': '零候选'}
                    self.status.set(statuses.get(result['status'], '未完成') + ' · ' +
                        ('工程回放（非实际推理）' if result['mode'] == 'replay' else '实际本机推理') +
                        '。候选未接收、全部待核。请预览原话、限定、位置和未完成范围。')
                    self.tabs.select(2)
                elif action == 'preview':
                    self._launch(result, '候选预览已打开；尚未接收。请回查逐字证据、限定和建议位置。')
                elif action in {'accept', 'saved'}:
                    if action == 'accept':
                        self.status.set('已接收为待核 · 已保存修订 ' + str(result['revision']) + '。请恢复并重开关注页，核对或纠正后应用草稿。')
                    else:
                        self._launch(self.target_path / 'attention.html', '保存态关注页已恢复并打开 · 修订 ' + str(result['revision']) + '。下载草稿后仍需应用。')
                    current = getattr(self.controller, 'attention_path', None)
                    if self.on_result and current is not None and Path(current).absolute() == self.target_path:
                        self.on_result(dict(kind='attention', path=self.target_path, revision=result['revision'], material_status=result['material_status']))
                elif action == 'start': self.status.set('本窗口启动的模型已运行。模型生成只在你点击生成时进行。')
                elif action == 'stop': self.status.set('本窗口启动的模型已停止。')
                self._controls()
        except queue.Empty:
            pass
        self.timer = self.window.after(80, self.poll)

    def _destroyed(self, event):
        if event.widget == self.window and self.timer:
            self.window.after_cancel(self.timer)
            self.timer = None

    @staticmethod
    def _open_file(path):
        if os.name == 'nt': os.startfile(path)
        else:
            import webbrowser
            require(webbrowser.open(path.as_uri()), 'E_BROWSER_OPEN')

    def _launch(self, path, message):
        try:
            self._open_file(path)
            self.status.set(message)
        except Exception:
            self.status.set('页面已生成，但浏览器未能打开。请检查本机默认浏览器，再点击预览或恢复并重开；保存状态不变。')

    def close(self):
        if self.busy:
            self.status.set('当前操作尚未结束。请等待完成后关闭，避免中断候选记录或保存。'); return
        if self.service.owned:
            self.status.set('本窗口仍拥有模型服务。请先在模型设置中停止，再关闭。'); return
        self.window.destroy()
