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
from .local_model_profiles import profiles, profile, DEFAULT_MODEL
from .attention_api_provider import DeepSeekProvider, API_MODELS, API_ENDPOINT, API_DEFAULT_TOKENS
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
            from .local_io import read_json, checked_local
            from .local_io import encoded
            from .core import digest
            receipt = checked_local(self.path / 'candidate-runs' / run_id / 'acceptance.json')
            if receipt.is_file():
                fingerprint = digest(encoded(read_json(receipt)))
                applied = next((h for h in current['history'] if h['fingerprint'] == fingerprint), None)
                run['accepted_revision'] = applied['revision'] if applied else None
        target = self.path / 'candidate-runs' / run_id / 'preview.html'
        from .local_io import atomic
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
    if code == 'E_DEEPSEEK_CREDENTIAL_MISSING':
        return '尚未配置DeepSeek。请在“更多选项 → 分析设置”中保存密钥。'
    if code == 'E_DEEPSEEK_CREDENTIAL_STORE':
        return 'API凭据无法保存或解密。请使用当前Windows用户重新保存，或显式设置DEEPSEEK_API_KEY。'
    if code == 'E_ATTENTION_API_MODEL':
        return 'API仅支持用户指定的DeepSeek 4.1 Flash / 1017，请选择deepseek-flash；不会改用Pro。'
    if code.startswith('E_ATTENTION_API'):
        return 'DeepSeek API操作未完成。请核对官方地址、模型和凭据；不会自动重试或改用本机模型。'
    if code == 'E_LOCAL_MODEL_MISSING':
        return '所选模型未安装。请由操作员按候选分析操作说明，将对应 GGUF 文件放入资源根目录的 .tools/local-llm 后重试；窗口不会下载。'
    if code == 'E_LOCAL_MODEL_WEIGHT':
        return '所选模型大小或 SHA-256 不符。请由操作员按候选分析操作说明核对固定文件版本并重新安装。'
    if code == 'E_ATTENTION_MODEL_PROFILE':
        return '模型名称不在已支持的固定配置中。请从模型下拉列表选择。'
    if code == 'E_ATTENTION_CAPACITY_PROFILE':
        return '表达分类需要至少768的输出长度以保留有界思考和完整结果。请将最大输出长度设为至少768后重新生成；本次未提高你设置的上限。'
    if code == 'E_ATTENTION_TARGET':
        return '目标或保存修订已变化。请关闭候选窗口，从当前分析包重新打开；原候选仍保留在原包。'
    if code == 'E_ATTENTION_REVALIDATION':
        return '来源、A或保存修订已变化，候选不能接收。请恢复关注页核对，并重新生成；旧记录保留。'
    if code == 'E_ATTENTION_OUTPUT_RECOVER':
        return '修改可能已经保存，但页面未能更新。请点击“查看已保存结果”重新打开。'
    if code in {'E_ATTENTION_ENDPOINT', 'E_ATTENTION_MODEL', 'E_ATTENTION_CAPACITY'}:
        return '模型设置无效。请核对提供方、服务地址、模型名称、输出长度和上下文上限。'
    if code == 'E_ATTENTION_NO_CANDIDATES':
        return '本次没有可接收候选。请查看预览中的未完成范围，调整选择后重新生成或人工补录。'
    if code.startswith('E_LOCAL_MODEL') or code == 'E_MODEL_NOT_OWNED':
        return '模型服务操作未完成。请核对已安装资源与独立运行目录，并检查端口是否已使用；不会接管其他进程。'
    return '操作未完成。请保留候选记录，恢复并重开关注页核对保存状态后重试。'


class CandidateModelService:
    """Separate ownership from the legacy extractor and from any existing port."""
    def __init__(self):
        self.owned = None

    def start(self, resource, runtime, model=DEFAULT_MODEL):
        from .desktop import ROOT, run_powershell
        require(self.owned is None, 'E_LOCAL_MODEL_OWNED')
        selected = profile(model)
        def matches_profile(state):
            if 'profile_id' not in state: return model == DEFAULT_MODEL
            return (state.get('profile_id') == model and state.get('model_id') == model and
                    state.get('model_sha256') == selected['sha256'] and state.get('model_size') == selected['size'])
        resource, runtime = Path(resource).resolve(), Path(runtime).absolute()
        result = run_powershell(['-ExecutionPolicy', 'Bypass', '-File', ROOT / 'scripts/start-local-model.ps1',
                                 '-ResourceRoot', resource, '-RuntimeDir', runtime, '-ModelId', model])
        output = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else result.stdout
        receipt = re.search(r'Owned PID (\d+) RUN ([0-9a-f]{32})', output or '')
        self.model_id = model
        if result.returncode != 0:
            # A stale state file alone never grants control. The current script
            # emits this receipt only after verifying its newly created process.
            if receipt:
                try:
                    state = json.loads((runtime / 'server-state.json').read_text(encoding='utf-8-sig'))
                    if (state.get('pid') == int(receipt[1]) and state.get('run_id') == receipt[2] and
                            Path(state.get('repo_root', '')).absolute() == ROOT and
                            state.get('owner') == 'ReviewProject/scripts/local-model/v1' and matches_profile(state)):
                        self.owned = (resource, runtime, state['run_id'])
                except (OSError, ValueError, TypeError):
                    pass
            details = str(getattr(result, 'stderr', ''))
            require('E_MODEL_MISSING' not in details, 'E_LOCAL_MODEL_MISSING')
            require('E_MODEL_SIZE' not in details and 'SHA-256' not in details, 'E_LOCAL_MODEL_WEIGHT')
            require(False, 'E_LOCAL_MODEL_START')
        state = json.loads((runtime / 'server-state.json').read_text(encoding='utf-8-sig'))
        require(receipt is not None and state.get('pid') == int(receipt[1]) and
                state.get('run_id') == receipt[2] and matches_profile(state) and
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
    def __init__(self, parent, controller, *, provider_factory=None, on_result=None):
        import tkinter as tk
        from tkinter import ttk
        from .desktop import ROOT
        from .native_ui import theme, wrapped, text_style, list_style, ScrollBody
        self.controller, self.provider_factory, self.on_result = controller, provider_factory, on_result
        self.session = CandidateSession(controller.attention_path)
        self.target_path = self.session.path
        self.service = CandidateModelService()
        self.results, self.busy, self.run_id = queue.Queue(), False, None
        self.accepted_run_id = None
        self.window = tk.Toplevel(parent)
        theme(self.window)
        self.window.title('分析评语')
        self.window.geometry('920x760'); self.window.minsize(760, 640)
        heading = ttk.Frame(self.window, padding=(24, 20, 24, 0)); heading.pack(fill='x')
        ttk.Label(heading, text='分析本批评语', style='Title.TLabel').pack(anchor='w')
        self.status = tk.StringVar(value='选好评语，开始分析。看过结果后再决定是否保存。')
        self.actor = tk.StringVar(value='本机使用者')
        self.reason = tk.StringVar(value='保存本次分析，保留待核状态。')
        self.provider = tk.StringVar(value='deepseek')
        self.endpoint = tk.StringVar(value=API_ENDPOINT)
        self.model = tk.StringVar(value=API_MODELS[0])
        self.api_key = tk.StringVar()
        self.credential_status = tk.StringVar(value='未检查；可点击检查配置。生成时读取已保存凭据或环境变量。')
        self.context_chars, self.max_tokens = tk.StringVar(value='24000'), tk.StringVar(value=str(API_DEFAULT_TOKENS))
        self.resource = tk.StringVar(value=str(ROOT))
        self.runtime = tk.StringVar(value=str(ROOT / 'work' / ('local-model-candidates-' + uuid.uuid4().hex[:12])))
        snapshot = self.session.snapshot
        target_label = ttk.Label(self.window, text='本次材料：' + str(len(snapshot['records'])) + ' 条评语 · ' +
            str(len(snapshot['a_reference']['items'])) + ' 项关注清单', wraplength=850)
        target_label.pack(fill='x', padx=24, pady=(12, 20))
        target_label.bind('<Configure>', lambda e: target_label.configure(wraplength=max(200, e.width)))
        footer = ttk.Frame(self.window, padding=14); footer.pack(side='bottom', fill='x')
        ttk.Separator(footer).pack(fill='x', pady=(0, 14))
        self.progress = ttk.Progressbar(footer, mode='indeterminate', takefocus=False)
        message = ttk.Label(footer, textvariable=self.status, wraplength=850)
        self.status_label = message
        message.pack(fill='x', pady=(0, 8)); message.bind('<Configure>', lambda e: message.configure(wraplength=max(200, e.width)))
        self.processing_note = tk.StringVar()
        wrapped(footer, textvariable=self.processing_note).pack(fill='x', pady=(0, 10))
        self.tabs = ttk.Notebook(self.window); self.tabs.pack(fill='both', expand=True, padx=14)
        records = ttk.Frame(self.tabs, padding=14); self.tabs.add(records, text='分析范围')
        toolbar = ttk.Frame(records); toolbar.pack(fill='x', pady=(0, 10))
        self.scope = tk.StringVar()
        ttk.Label(toolbar, textvariable=self.scope, style='Heading.TLabel').pack(side='left')
        def select_all():
            self.record_list.selection_set(0, 'end'); self.selection_changed()
        ttk.Button(toolbar, text='全选评语', command=select_all).pack(side='right')
        wrapped(records, text='选择本次要分析的评语。可用 Ctrl / Shift 多选；选中后在下方核对原话。').pack(fill='x', pady=(0, 12))
        record_frame = ttk.Frame(records); record_frame.pack(fill='both', expand=True)
        self.record_list = tk.Listbox(record_frame, selectmode='extended', exportselection=False, height=6)
        list_style(self.record_list)
        scrollbar = ttk.Scrollbar(record_frame, command=self.record_list.yview)
        self.record_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y'); self.record_list.pack(fill='both', expand=True)
        self.record_ids = [r['record_id'] for r in self.session.snapshot['records']]
        for number, record in enumerate(self.session.snapshot['records'], 1):
            name = '评语 ' + str(number) if record['anchor'].startswith('手工录入-') else record['anchor']
            self.record_list.insert('end', name + '  ·  ' + record['text'][:80].replace('\n', ' '))
        self.record_list.selection_set(0, 'end')
        original_label = ttk.Label(records, text='原话 · 当前选中评语', style='Muted.TLabel')
        original_frame = ttk.Frame(records); original_frame.pack(side='bottom', fill='x')
        original_label.pack(side='bottom', anchor='w', pady=(16, 8))
        self.original = tk.Text(original_frame, height=4, wrap='word', state='disabled', takefocus=True)
        text_style(self.original)
        original_scroll = ttk.Scrollbar(original_frame, command=self.original.yview)
        self.original.configure(yscrollcommand=original_scroll.set)
        original_scroll.pack(side='right', fill='y'); self.original.pack(fill='x')
        # Reserve the readable original before giving the checklist spare height.
        record_frame.pack_forget(); record_frame.pack(fill='both', expand=True)
        self.record_list.bind('<<ListboxSelect>>', lambda event: self.selection_changed())
        model_container = ttk.Frame(self.tabs); self.tabs.add(model_container, text='分析设置')
        settings = ScrollBody(model_container, padding=14); settings.pack(fill='both', expand=True)
        model_tab = settings.body
        model_note = ttk.Label(model_tab, text='DeepSeek API将联网发送所选普通评语及本次A，原话可能含身份；原分和本地路径不发送。点击生成即按所选提供方处理。也可选择已安装本机模型；仅本窗口启动的实例可由本窗口停止。', wraplength=750)
        model_note.pack(fill='x', pady=5)
        model_note.bind('<Configure>', lambda e: model_note.configure(wraplength=max(200, e.width)))
        def entry(parent, label, variable):
            ttk.Label(parent, text=label).pack(anchor='w')
            e = ttk.Entry(parent, textvariable=variable); e.pack(fill='x', pady=(0, 6)); return e
        ttk.Label(model_tab, text='模型提供方').pack(anchor='w')
        self.provider_selector = ttk.Combobox(model_tab,textvariable=self.provider,state='readonly',values=('deepseek','local'))
        self.provider_selector.pack(fill='x',pady=(0,6))
        self.provider_selector.bind('<<ComboboxSelected>>',lambda e:self.change_provider())
        self.endpoint_entry = entry(model_tab, '服务地址（API限定官方HTTPS；本机限定回环）', self.endpoint)
        ttk.Label(model_tab, text='模型名称（本机模型需事先安装）').pack(anchor='w')
        self.model_selector = ttk.Combobox(model_tab, textvariable=self.model, state='readonly', values=API_MODELS)
        self.model_selector.pack(fill='x', pady=(0,6))
        self.api_settings = ttk.Frame(model_tab); self.api_settings.pack(fill='x')
        ttk.Label(self.api_settings,text='DeepSeek API密钥（输入后显式保存，仅当前Windows用户可解密）').pack(anchor='w')
        self.key_entry=ttk.Entry(self.api_settings,textvariable=self.api_key,show='*'); self.key_entry.pack(fill='x')
        credential_row=ttk.Frame(self.api_settings); credential_row.pack(fill='x')
        self.save_key_button=ttk.Button(credential_row,text='保存API密钥',command=self.save_api_key); self.save_key_button.pack(side='left')
        self.check_key_button=ttk.Button(credential_row,text='检查API配置',command=self.check_api_key); self.check_key_button.pack(side='left',padx=8)
        wrapped(self.api_settings, textvariable=self.credential_status).pack(fill='x', pady=(8, 12))
        row = ttk.Frame(model_tab); row.pack(fill='x')
        for label, value in [('输入字符上限（整段超限会明确列出）', self.context_chars), ('最大输出长度（API含思考token）', self.max_tokens)]:
            col = ttk.Frame(row); col.pack(side='left', fill='x', expand=True, padx=(0, 10)); entry(col, label, value)
        self.local_settings = ttk.Frame(model_tab)
        entry(self.local_settings, '已安装资源根目录（含 .tools/local-llm）', self.resource)
        from tkinter import filedialog
        def choose_resource():
            path = filedialog.askdirectory(parent=self.window, title='选择已有模型资源根目录')
            if path: self.resource.set(path)
        ttk.Button(self.local_settings, text='选择已安装资源目录', command=choose_resource).pack(anchor='w')
        entry(self.local_settings, '本次独立运行目录（新的空目录）', self.runtime)
        def choose_runtime():
            path = filedialog.askdirectory(parent=self.window, title='选择父目录，将建立独立运行子目录')
            if path: self.runtime.set(str(Path(path) / ('local-model-' + uuid.uuid4().hex[:12])))
        ttk.Button(self.local_settings, text='选择运行目录的父目录', command=choose_runtime).pack(anchor='w')
        service_row = ttk.Frame(self.local_settings); service_row.pack(fill='x', pady=8)
        self.start_button = ttk.Button(service_row, text='启动已安装模型', command=self.start_service); self.start_button.pack(side='left')
        self.stop_button = ttk.Button(service_row, text='停止本窗口启动的模型', command=self.stop_service); self.stop_button.pack(side='left', padx=8)
        history = ttk.Frame(self.tabs, padding=10); self.tabs.add(history, text='以往结果')
        wrapped(history, text='固定保存位置：' + str(self.target_path)).pack(fill='x', pady=8)
        self.history = ttk.Combobox(history, state='readonly', values=self.session.runs()); self.history.pack(fill='x', pady=8)
        self.history.bind('<<ComboboxSelected>>', lambda e: self.select_run())
        entry(history, '操作人', self.actor); entry(history, '保存备注', self.reason)
        self.restart_button = ttk.Button(history, text='重新分析所选评语', command=self.generate); self.restart_button.pack(anchor='w', pady=8)
        self.open_button = ttk.Button(history, text='查看已保存结果', command=self.open_saved); self.open_button.pack(anchor='w')
        self.generate_button = ttk.Button(footer, text='开始分析', style='Primary.TButton', command=self.generate)
        self.preview_button = ttk.Button(footer, text='查看结果', style='Primary.TButton', command=self.open_preview)
        self.accept_button = ttk.Button(footer, text='保存分析', command=self.accept)
        self.options_button = ttk.Button(footer, text='模型与历史…', command=self.toggle_options); self.options_button.pack(side='right')
        self.records_tab, self.settings_tab, self.history_tab = records, model_container, history
        self.options_open = False
        self.tabs.hide(self.settings_tab); self.tabs.hide(self.history_tab)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.selection_changed(); self.timer = self.window.after(80, self.poll)
        self.window.bind('<Destroy>', self._destroyed, add='+')

    def selection_changed(self):
        selected = self.record_list.curselection()
        self.scope.set('已选 ' + str(len(selected)) + ' / ' + str(len(self.record_ids)) + ' 条评语')
        self.original.configure(state='normal'); self.original.delete('1.0', 'end')
        if selected:
            index = self.record_list.index('active')
            if index not in selected: index = selected[0]
            self.original.insert('1.0', self.session.snapshot['records'][index]['text'])
        else:
            self.original.insert('1.0', '尚未选择评语。请在上方选择本次分析范围。')
        self.original.configure(state='disabled')
        self._controls()

    def _controls(self):
        for b in (self.generate_button, self.restart_button, self.open_button, self.start_button):
            b.configure(state='disabled' if self.busy else 'normal')
        for b in (self.preview_button, self.accept_button):
            b.configure(state='normal' if self.run_id and not self.busy else 'disabled')
        self.stop_button.configure(state='normal' if self.service.owned and not self.busy else 'disabled')
        self.history.configure(state='disabled' if self.busy else 'readonly')
        if not self.record_list.curselection():
            self.generate_button.configure(state='disabled'); self.restart_button.configure(state='disabled')
        if self.busy:
            self.progress.pack(fill='x', before=self.status_label, pady=(0, 10))
        else:
            self.progress.pack_forget()
        api=self.provider.get()=='deepseek'
        self.provider_selector.configure(state='disabled' if self.busy else 'readonly')
        self.model_selector.configure(state='disabled' if self.busy or (self.service.owned and not api) else 'readonly')
        self.endpoint_entry.configure(state='disabled' if self.busy else 'normal')
        self.start_button.configure(state='disabled' if self.busy or api or self.service.owned else 'normal')
        for widget in (self.key_entry,self.save_key_button,self.check_key_button):
            widget.configure(state='normal' if api and not self.busy else 'disabled')
        self.processing_note.set('通过 DeepSeek 分析所选评语和本次关注清单。' if api else '通过本机模型分析所选材料。')
        for button in (self.generate_button, self.preview_button, self.accept_button):
            button.pack_forget()
        if self.run_id:
            self.preview_button.configure(command=self.open_saved if self.run_id == self.accepted_run_id else self.open_preview)
            self.preview_button.pack(side='left')
            if self.run_id != self.accepted_run_id:
                self.accept_button.pack(side='left', padx=8)
        else:
            self.generate_button.pack(side='left')

    def toggle_options(self):
        self.options_open = not self.options_open
        if self.options_open:
            self.tabs.add(self.settings_tab); self.tabs.add(self.history_tab)
        else:
            self.tabs.select(self.records_tab)
            self.tabs.hide(self.settings_tab); self.tabs.hide(self.history_tab)
        self.options_button.configure(text='收起模型与历史' if self.options_open else '模型与历史…')

    def change_provider(self):
        if self.busy: return
        api=self.provider.get()=='deepseek'
        self.model_selector.configure(values=API_MODELS if api else list(profiles()))
        self.model.set(API_MODELS[0] if api else getattr(self.service,'model_id',DEFAULT_MODEL))
        self.endpoint.set(API_ENDPOINT if api else 'http://127.0.0.1:8766/v1')
        self.max_tokens.set(str(API_DEFAULT_TOKENS) if api else '4096')
        self.api_key.set('')
        self.api_settings.pack_forget(); self.local_settings.pack_forget()
        (self.api_settings if api else self.local_settings).pack(fill='x')
        self._controls()

    def check_api_key(self):
        from .credential import credential_available
        self.credential_status.set('已配置（生成时核验凭据可用性）' if credential_available() else
            '缺失：输入并保存API密钥，或设置DEEPSEEK_API_KEY环境变量。')

    def save_api_key(self):
        from .credential import save_deepseek_key
        try:
            save_deepseek_key(self.api_key.get())
            self.credential_status.set('已保存（仅当前Windows用户可解密；显式环境变量优先）。')
        except Exception as exc:
            self.credential_status.set(candidate_message(exc))
        finally:
            self.api_key.set('')

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
        self.status_label.configure(style='TLabel')
        results = self.results
        def execute():
            try: results.put((action, worker(), None))
            except Exception as exc: results.put((action, None, exc))
        threading.Thread(target=execute, daemon=True).start()

    def generate(self):
        if self.busy or not self._target_current(): return
        ids = [self.record_ids[i] for i in self.record_list.curselection()]
        if not ids:
            self.status.set('请至少选择一条评语。'); return
        try:
            chars, tokens = int(self.context_chars.get()), int(self.max_tokens.get())
            if self.provider.get()=='deepseek' and self.api_key.get():
                self.status.set('请先点击保存API密钥，再生成候选。'); return
            factory=self.provider_factory or (DeepSeekProvider if self.provider.get()=='deepseek' else LocalProvider)
            provider = factory(endpoint=self.endpoint.get(), model=self.model.get(), max_tokens=tokens)
        except Exception as exc:
            from .core import ReviewError
            self.status.set(candidate_message(exc) if isinstance(exc,ReviewError) else '请核对模型设置；输入和输出上限须为有效整数。'); return
        run_id = 'desktop-' + uuid.uuid4().hex
        session = self.session
        self.submit('generate', lambda: session.generate(run_id, provider, ids, chars))

    def select_run(self):
        self.run_id = self.history.get() or None; self._controls()
        self.status.set('已选中以往结果。可先查看，再决定是否保存。')

    def open_preview(self):
        run_id, session = self.run_id, self.session
        if run_id: self.submit('preview', lambda: session.preview(run_id))

    def accept(self):
        if self.busy or not self.run_id or not self._target_current(): return
        actor = self.actor.get().strip() or '本机使用者'
        reason = self.reason.get().strip() or '保存本次分析，保留待核状态。'
        run_id = self.run_id
        session = self.session
        self.submit('accept', lambda: session.accept(run_id, actor=actor, reason=reason))

    def open_saved(self):
        if not self._target_current(): return
        path = self.target_path
        def recover():
            with closing(AttentionWorkspace(path)) as ws: return ws.recover()
        self.submit('saved', recover)

    def start_service(self):
        if self.provider.get()!='local': return
        resource, runtime, service = self.resource.get(), self.runtime.get(), self.service
        model = self.model.get()
        self.submit('start', lambda: service.start(resource, runtime, model))

    def stop_service(self):
        self.submit('stop', self.service.stop)

    def poll(self):
        if self.busy:
            self.progress.step(4)
        try:
            while True:
                action, result, error = self.results.get_nowait()
                self.busy = False
                if error:
                    self.status_label.configure(style='Status.TLabel')
                    self.status.set('模型尚未就绪。本窗口已保留此次进程身份，请在模型设置中点击停止后重试。'
                        if action == 'start' and self.service.owned else candidate_message(error))
                elif action == 'generate':
                    self.status_label.configure(style='Status.TLabel')
                    self.run_id = result['run_id']; self.history.configure(values=self.session.runs()); self.history.set(self.run_id)
                    statuses = {'complete': '分析完成', 'partial': '部分内容未完成', 'failed': '分析未完成', 'zero_candidates': '没有生成结果'}
                    self.status.set(statuses.get(result['status'], '未完成') + ' · ' +
                        ('工程回放（非实际推理）' if result['mode'] == 'replay' else 'DeepSeek API联网推理' if result['mode']=='remote_api' else '实际本机推理') +
                        '。请查看结果，核对后保存。')
                    if result.get('errors'):
                        code=result['errors'][0]['code']
                        if code.startswith('E_DEEPSEEK_') or code.startswith('E_ATTENTION_API'):
                            self.status.set(self.status.get()+' '+candidate_message(code))
                elif action == 'preview':
                    self._launch(result, '结果已打开，尚未保存。')
                elif action in {'accept', 'saved'}:
                    if action == 'accept':
                        self.accepted_run_id = self.run_id
                        self._launch_current('分析已保存并打开，内容仍待核对。')
                    else:
                        self._launch_current('已打开保存的分析结果。')
                    current = getattr(self.controller, 'attention_path', None)
                    if self.on_result and current is not None and Path(current).absolute() == self.target_path:
                        self.on_result(dict(kind='attention', path=self.target_path, revision=result['revision'], material_status=result['material_status']))
                elif action == 'start':
                    if self.provider.get()=='local':
                        self.model.set(self.service.model_id)
                        self.endpoint.set('http://127.0.0.1:8766/v1')
                    self.status.set('本窗口启动的模型已运行。模型生成只在你点击生成时进行。')
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

    def _launch_current(self, message):
        try:
            self.controller.open_attention_report(self.target_path)
            self.status.set(message)
        except Exception:
            self.status.set('分析保存状态不变，浏览器未能打开。请重新点击查看结果。')

    def _launch(self, path, message):
        try:
            self._open_file(path)
            self.status.set(message)
        except Exception:
            self.status.set('页面已生成，但浏览器未能打开。请检查默认浏览器，再点“查看结果”；保存状态不变。')

    def close(self):
        if self.busy:
            self.status.set('当前操作尚未结束。请等待完成后关闭，避免中断候选记录或保存。'); return
        if self.service.owned:
            self.status.set('本窗口仍拥有模型服务。请先在模型设置中停止，再关闭。'); return
        self.window.destroy()
