"""Small local launcher; Tk and model dependencies are loaded only on demand."""
from contextlib import closing
from pathlib import Path
import os
import json
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

from .core import ReviewError, require
from .store import Workspace, linklike

ROOT = Path(__file__).resolve().parents[1]
# Fixed read-only identity probe. No source text or user path is shell code.
MODEL_IDENTITY = r"""
$ErrorActionPreference = 'Stop'
try {
  $s = Get-Content -LiteralPath 'work/local-model/server-state.json' -Raw | ConvertFrom-Json
  $exe = Join-Path (Get-Location).Path '.tools/local-llm/llama-b12110-vulkan/llama-server.exe'
  if ($s.owner -ne 'ReviewProject/scripts/local-model/v1' -or $s.repo_root -ne (Get-Location).Path -or $s.executable -ne $exe) { exit 2 }
  $p = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$s.pid)
  $proc = Get-Process -Id $s.pid
  if (-not $p -or $p.ExecutablePath -ne $exe -or -not $p.CommandLine.EndsWith($s.arguments, [StringComparison]::Ordinal) -or
      $proc.StartTime.ToUniversalTime().Ticks -ne $s.process_start_ticks_utc -or
      -not $p.CommandLine.Contains('--tags reviewproject-local-run-' + $s.run_id)) { exit 2 }
  $listeners = @(Get-NetTCPConnection -LocalPort 8766 -State Listen)
  if ($listeners.Count -eq 0 -or @($listeners | Where-Object { $_.OwningProcess -ne $s.pid -or $_.LocalAddress -ne '127.0.0.1' }).Count -gt 0) { exit 2 }
  Write-Output $s.run_id
} catch { exit 2 }
"""


def safe_message(error):
    code = str(error) if isinstance(error, ReviewError) and re.fullmatch(r'E_[A-Z0-9_]+', str(error)) else 'E_INTERNAL'
    if code == 'E_ATTENTION_CONFLICT':
        return code + '：关注补丁修订已过期。请恢复关注页并重开，重新导出修改；不会自动改写修订号。'
    if code == 'E_ATTENTION_REVALIDATION':
        return code + '：来源或A参照待核，旧快照已保留。请恢复关注页核对输入绑定；不能继续应用或静默转绑。'
    if code == 'E_ATTENTION_OUTPUT_RECOVER':
        return code + '：关注修改可能已提交，但页面输出失败。请恢复关注页并重开核对保存修订；不要改写补丁修订号。'
    if code in {'E_ATTENTION_NOT_DEDICATED', 'E_ATTENTION_DIRECTORY', 'E_ATTENTION_EXISTS'}:
        return code + '：目标已有文件或分析，已保护原内容。请另选空目录或建立独立新子目录。'
    if code.startswith('E_ATTENTION_'):
        return code + '：关注分析操作未完成。请保留所选文件，使用“恢复关注页”核对当前修订。'
    if code in {'E_REVISION_CONFLICT', 'E_PATCH_REVISION'}:
        return code + '：补丁修订已过期。请重新打开报告，重新导出修改；不会自动改写修订号。'
    if code == 'E_OUTPUT_FAILED':
        return code + '：修改已提交，但报告输出失败。请使用“恢复报告”，再重新打开核对；不要改写补丁修订号。'
    if code.startswith('E_LOCAL_MODEL') or code == 'E_MODEL_NOT_OWNED':
        return code + '：请核对本机已安装模型与项目服务状态。不会下载或接管其他实例；启动失败的实例请由原启动窗口或项目脚本核对停止。'
    if code.startswith('E_BATCH_'):
        return code + '：审核包操作未完成。请恢复审核包并重开核对；观点拆分或补录后用“重选观点并刷新包”。旧建议需重新分析，旧决定需复核。'
    return code + '：操作未完成；保存可能已提交。请保留所选文件，使用“恢复报告”核对当前修订后重试。'


def run_process(argv):
    # A service launched by the direct child may retain its output handles.
    # Files let us wait for that child without waiting for pipe EOF from the
    # service. Capture a finite snapshot without waiting for later output.
    with tempfile.TemporaryFile(mode='w+b') as stdout, tempfile.TemporaryFile(mode='w+b') as stderr:
        result = subprocess.run([str(v) for v in argv], cwd=ROOT, shell=False,
                                stdout=stdout, stderr=stderr,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
        for name, stream in [('stdout', stdout), ('stderr', stderr)]:
            size = os.fstat(stream.fileno()).st_size
            stream.seek(0)
            setattr(result, name, stream.read(size))
        return result


def powershell_executable():
    # Prefer the same modern host used by the project scripts on this machine.
    # Resolve once per invocation as an executable value, never as shell text.
    executable = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
    require(executable is not None, 'E_LOCAL_MODEL_SETUP')
    return str(Path(executable).absolute())


def run_powershell(arguments):
    return run_process([powershell_executable(), '-NoProfile', *arguments])


class Controller:
    def __init__(self):
        self.path = None
        self.batch_path = None

    def build_attention(self, source, destination):
        from .attention import AttentionWorkspace
        self.attention_path = Path(destination).absolute()
        ws = AttentionWorkspace(self.attention_path)
        try:
            return self._attention_result(ws.build(input_path=source))
        finally:
            ws.close()

    def build_prepared_attention(self, draft, destination):
        from .attention_input import build_prepared
        def committed(path):
            self.attention_path = path
        return self._attention_result(build_prepared(draft, destination, on_committed=committed))

    def import_prepared_attention_a(self, reference, actor, reason):
        from .attention import AttentionWorkspace
        from .attention_input import import_prepared_a
        require(getattr(self, 'attention_path', None) is not None, 'E_ATTENTION_EMPTY')
        with closing(AttentionWorkspace(self.attention_path)) as ws:
            return self._attention_result(import_prepared_a(ws, reference, actor, reason))

    def _attention_result(self, state):
        return {'kind': 'attention', 'path': self.attention_path, 'revision': state['revision'], 'material_status': state['material_status']}

    def migrate_attention(self, source, destination, actor, reason):
        from .attention import AttentionWorkspace
        self.attention_path = Path(destination).absolute()
        ws = AttentionWorkspace(self.attention_path)
        try:
            return self._attention_result(ws.migrate_working_draft(source, actor=actor, reason=reason))
        finally:
            ws.close()

    def open_attention(self, path):
        from .attention import AttentionWorkspace
        path = Path(path).absolute()
        require((path / 'attention.sqlite3').is_file(), 'E_ATTENTION_EMPTY')
        self.attention_path = path
        return self.recover_attention()

    def recover_attention(self):
        from .attention import AttentionWorkspace
        require(getattr(self, 'attention_path', None) is not None, 'E_ATTENTION_EMPTY')
        ws = AttentionWorkspace(self.attention_path)
        try:
            return self._attention_result(ws.recover())
        finally:
            ws.close()

    def apply_attention(self, patch):
        from .attention import AttentionWorkspace
        require(getattr(self, 'attention_path', None) is not None, 'E_ATTENTION_EMPTY')
        ws = AttentionWorkspace(self.attention_path)
        try:
            return self._attention_result(ws.apply(input_path=patch))
        finally:
            ws.close()

    def import_attention_a(self, source, actor, reason):
        from .attention import AttentionWorkspace
        require(getattr(self, 'attention_path', None) is not None, 'E_ATTENTION_EMPTY')
        ws = AttentionWorkspace(self.attention_path)
        try:
            return self._attention_result(ws.import_a(source, actor=actor, reason=reason))
        finally:
            ws.close()

    def open_attention_report(self):
        self.recover_attention()
        if os.name == 'nt':
            os.startfile(self.attention_path / 'attention.html')
        else:
            import webbrowser
            require(webbrowser.open((self.attention_path / 'attention.html').as_uri()), 'E_BROWSER_OPEN')
        return self.recover_attention()

    def _batch_existing(self):
        from .batch import checked_local
        require(self.batch_path is not None, 'E_BATCH_MISSING')
        path = checked_local(self.batch_path)
        require((path / 'batch.sqlite3').is_file(), 'E_BATCH_MISSING')
        return path

    def _batch_result(self, state, **extra):
        return dict(kind='batch', path=self.batch_path, batch_id=state['batch_id'], revision=state['revision'],
                    material_status=state['material_status'],
                    sources=[dict(source_id=s['source']['source_id'], workspace=s['workspace']) for s in state['sources']], **extra)

    def open_batch(self, path):
        from .batch import BatchWorkspace, checked_local
        target = checked_local(path)
        require((target / 'batch.sqlite3').is_file(), 'E_BATCH_MISSING')
        self.batch_path = target
        return self.recover_batch()

    def recover_batch(self):
        from .batch import BatchWorkspace
        with closing(BatchWorkspace(self._batch_existing())) as ws:
            return self._batch_result(ws.recover())

    def apply_batch(self, patch):
        from .batch import BatchWorkspace
        with closing(BatchWorkspace(self._batch_existing())) as ws:
            before = ws.state()['revision']
            state = ws.apply(input_path=patch)
            return self._batch_result(state, idempotent=state['revision'] == before)

    def batch_refresh_options(self):
        from .batch import BatchWorkspace
        with closing(BatchWorkspace(self._batch_existing())) as ws:
            return ws.refresh_options()

    def refresh_batch(self, selection=None):
        from .batch import BatchWorkspace
        with closing(BatchWorkspace(self._batch_existing())) as ws:
            return self._batch_result(ws.refresh(selection))

    def open_batch_source(self, source_id):
        from .batch import BatchWorkspace
        with closing(BatchWorkspace(self._batch_existing())) as ws:
            source = next((s for s in ws.state()['sources'] if s['source']['source_id'] == source_id), None)
            require(source is not None, 'E_BATCH_SOURCE_ID')
            path = source['workspace']
        return self.open_workspace(path)

    def open_batch_report(self):
        path = self._batch_existing() / 'report.html'
        require(path.is_file() and not linklike(path), 'E_REPORT_MISSING')
        if os.name == 'nt':
            os.startfile(path)
        else:
            import webbrowser
            webbrowser.open(path.as_uri())

    @staticmethod
    def _existing(path):
        require(path is not None, 'E_WORKSPACE_MISSING')
        path = Path(path).absolute()
        require((path / 'review.sqlite3').is_file(), 'E_WORKSPACE_MISSING')
        return path

    def _result(self, state, **extra):
        return {'path': self.path, 'revision': state['revision'], 'origin': state['source']['origin'],
                'sections': [{'section_id': s['section_id'], 'label': s['label']} for s in state['sections']
                             if s['visibility'] != 'internal_only'], **extra}

    @staticmethod
    def _mutation(ws, action):
        try:
            return action()
        except Exception:
            # Operation records explicitly distinguish committed-but-unpublished
            # data. Never infer that an exception means a rollback.
            record = ws.db.execute('SELECT payload FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
            if record and json.loads(record[0]).get('status') == 'output_failed':
                raise ReviewError('E_OUTPUT_FAILED') from None
            raise

    def import_source(self, source, destination, origin, source_format):
        destination = Path(destination).absolute()
        require(not any(linklike(p) for p in [destination, *destination.parents]), 'E_WORKSPACE_LINK')
        require(not destination.exists() or destination.is_dir() and not any(destination.iterdir()), 'E_WORKSPACE_NOT_DEDICATED')
        # Keep the location on failure: a failed publication may follow a commit.
        self.path = destination
        with closing(Workspace(destination)) as ws:
            return self._result(self._mutation(ws, lambda: ws.run(source, origin, source_format)))

    def open_workspace(self, path):
        target = self._existing(path)
        # Recovery republishes the current editor for pre-upgrade workspaces;
        # it preserves the revision and all saved business records.
        self.path = target
        with closing(Workspace(target)) as ws:
            state = self._mutation(ws, ws.recover)
        return self._result(state)

    def apply_patch(self, patch):
        with closing(Workspace(self._existing(self.path))) as ws:
            before = ws.state()['revision']
            state = self._mutation(ws, lambda: ws.apply(input_path=patch))
            return self._result(state, idempotent=state['revision'] == before)

    def recover(self):
        with closing(Workspace(self._existing(self.path))) as ws:
            return self._result(self._mutation(ws, ws.recover))

    def open_report(self):
        path = self._existing(self.path) / 'report.html'
        require(path.is_file() and not linklike(path), 'E_REPORT_MISSING')
        if os.name == 'nt':
            os.startfile(path)
        else:
            import webbrowser
            webbrowser.open(path.as_uri())

    def start_model(self):
        # This window may stop only a service it successfully started.
        require(not getattr(self, 'owns_model', False), 'E_MODEL_ALREADY_STARTED')
        result = run_powershell(['-ExecutionPolicy', 'Bypass', '-File', ROOT / 'scripts/start-local-model.ps1'])
        require(result.returncode == 0, 'E_LOCAL_MODEL_START')
        state = json.loads((ROOT / 'work/local-model/server-state.json').read_text(encoding='utf-8-sig'))
        output = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else result.stdout
        match = re.search(r'PID (\d+)', output or '')
        require(match is not None and state.get('pid') == int(match[1]), 'E_MODEL_NOT_OWNED')
        self.owns_model = state['run_id']

    def retrieve_batch(self, query_path, method, model_path=None, top_k=10):
        from .batch import BatchWorkspace
        from .batch_retrieval import retrieve
        with closing(BatchWorkspace(self._batch_existing())) as ws:
            retrieve(ws, query_path=query_path, method=method, model_path=model_path,
                     top_k=top_k, run_id='desktop-search-' + uuid.uuid4().hex)
            return self._batch_result(ws.state())

    def retrieve_batch_text(self, query, method, model_path=None, top_k=10):
        require(isinstance(query, str) and query.strip() and len(query) <= 4000, 'E_RETRIEVAL_QUERY')
        with tempfile.TemporaryDirectory(prefix='review-search-') as folder:
            path = Path(folder) / 'query.txt'
            path.write_text(query, encoding='utf-8')
            return self.retrieve_batch(path, method, model_path, top_k)

    def extract_approved(self, plan, approval, alias, section):
        from .approved_extraction import launch
        summary = launch(self._existing(self.path), plan, approval, alias, section, 'desktop-flash-' + uuid.uuid4().hex)
        with closing(Workspace(self.path)) as ws:
            return self._result(ws.state(), extraction=summary)

    def stop_model(self):
        require(getattr(self, 'owns_model', False), 'E_MODEL_NOT_OWNED')
        state = json.loads((ROOT / 'work/local-model/server-state.json').read_text(encoding='utf-8-sig'))
        require(state.get('run_id') == self.owns_model, 'E_MODEL_NOT_OWNED')
        result = run_powershell(['-ExecutionPolicy', 'Bypass', '-File',
                                 ROOT / 'scripts/stop-local-model.ps1', '-ExpectedRunId', self.owns_model])
        require(result.returncode == 0, 'E_LOCAL_MODEL_STOP')
        self.owns_model = False

    def _check_model(self):
        require(getattr(self, 'owns_model', False), 'E_MODEL_NOT_OWNED')
        result = run_powershell(['-Command', MODEL_IDENTITY])
        output = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else result.stdout
        require(result.returncode == 0 and (output or '').strip() == self.owns_model, 'E_MODEL_NOT_OWNED')

    def extract(self, section):
        self._check_model()
        with closing(Workspace(self._existing(self.path))) as ws:
            state = ws.state()
            require(any(s['section_id'] == section and s['visibility'] != 'internal_only' for s in state['sections']), 'E_EXTRACTION_SECTIONS')
        python = ROOT / '.tools/semantic-env/Scripts/python.exe'
        require(python.is_file(), 'E_LOCAL_MODEL_SETUP')
        run_id = 'desktop-' + uuid.uuid4().hex
        result = run_process([python, ROOT / 'experiments/extract_local.py', '--workspace', self.path,
                              '--section', section, '--protocol', 'v3', '--run-id', run_id])
        payload = self.path / 'model-artifacts' / run_id / 'candidates.json'
        # Exit 2 with a persisted failed payload is still imported for audit.
        require(result.returncode in {0, 2} and payload.is_file(), 'E_LOCAL_EXTRACTION_FAILED')
        with closing(Workspace(self._existing(self.path))) as ws:
            state = self._mutation(ws, lambda: ws.import_extractions(input_path=payload))
            return self._result(state, extraction=ws.last_import_summary)


def main():
    try:
        import tkinter as tk
        from tkinter import filedialog, simpledialog, ttk
    except ImportError:
        raise ReviewError('E_DESKTOP_UNAVAILABLE') from None

    root = tk.Tk()
    root.title('ReviewProject · 可信编辑本机入口')
    root.geometry('800x920')
    controller, results = Controller(), queue.Queue()
    busy = False
    widgets = []
    status = tk.StringVar(value='选择新材料或已有工作区。材料、报告和补丁仅供可信编辑。')
    location = tk.StringVar(value='尚未打开工作区')
    batch_location = tk.StringVar(value='尚未选择审核包；下载决定不等于已保存。')
    batch_source = tk.StringVar()
    origin_labels = {'unknown': '未确认', 'original_review': '原始审稿', 'synthetic': '合成演示'}
    origin = tk.StringVar(value=origin_labels['unknown'])
    source_format = tk.StringVar(value='docx')
    section = tk.StringVar()
    ttk.Label(root, textvariable=status, wraplength=750).pack(fill='x', padx=16, pady=10)
    outer = tk.Canvas(root, highlightthickness=0)
    outer_scroll = ttk.Scrollbar(root, orient='vertical', command=outer.yview)
    outer.configure(yscrollcommand=outer_scroll.set)
    outer_scroll.pack(side='right', fill='y')
    outer.pack(fill='both', expand=True)
    frame = ttk.Frame(outer, padding=16)
    outer_window = outer.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda e: outer.configure(scrollregion=outer.bbox('all')))
    outer.bind('<Configure>', lambda e: outer.itemconfigure(outer_window, width=e.width))
    ttk.Label(frame, text='可信编辑工作区', font=('', 16)).pack(anchor='w')
    ttk.Label(frame, textvariable=location, wraplength=700).pack(anchor='w', pady=10)
    options = ttk.Frame(frame)
    options.pack(fill='x')
    for label, variable, choices in [('来源声明', origin, list(origin_labels.values())),
                                       ('输入类型', source_format, ['docx', 'csv', 'json'])]:
        ttk.Label(options, text=label).pack(side='left')
        box = ttk.Combobox(options, textvariable=variable, values=choices, state='readonly', width=17)
        box.pack(side='left', padx=6)
        widgets.append(box)

    def submit(action, success='操作完成'):
        nonlocal busy
        if busy:
            return
        busy = True
        status.set('处理中，请等待；关闭前需等当前操作结束。')
        for widget in widgets:
            widget.configure(state='disabled')

        def work():
            try:
                results.put((action(), None, success))
            except Exception as error:
                results.put((None, safe_message(error), success))
        # Non-daemon: closing the launcher never kills an in-flight apply.
        threading.Thread(target=work, daemon=False).start()

    def poll():
        nonlocal busy
        try:
            result, error, success = results.get_nowait()
        except queue.Empty:
            pass
        else:
            busy = False
            for widget in widgets:
                widget.configure(state='readonly' if isinstance(widget, ttk.Combobox) else 'normal')
            if error:
                status.set(error)
                if controller.path:
                    location.set(str(controller.path) + ' · 保存状态待恢复核对')
            else:
                status.set(success)
                if isinstance(result, dict) and result.get('kind') == 'attention':
                    attention_location.set(str(result['path']) + ' · 已保存修订 ' + str(result['revision']) + ' · ' + result['material_status'])
                elif isinstance(result, dict) and result.get('kind') == 'batch':
                    batch_location.set(str(result['path']) + ' · 审核包 ' + result['batch_id'] + ' · 已保存修订 ' + str(result['revision']) + ' · 材料 ' + result['material_status'])
                    batch_source_box['values'] = [s['source_id'] for s in result['sources']]
                    if batch_source.get() not in batch_source_box['values']:
                        batch_source.set(result['sources'][0]['source_id'] if result['sources'] else '')
                    if result.get('idempotent'):
                        status.set('同一审核决定已应用；幂等重放，修订不变。请重开审核页核对。')
                elif isinstance(result, dict) and result.get('show_refresh_choices'):
                    show_refresh_choices(result['options'])
                elif isinstance(result, dict):
                    location.set(str(result['path']) + ' · 已保存修订 ' + str(result['revision']) + ' · 来源 ' + origin_labels[result['origin']])
                    section_box['values'] = [s['section_id'] for s in result['sections']]
                    if section.get() not in section_box['values']:
                        section.set(result['sections'][0]['section_id'] if result['sections'] else '')
                    if result.get('idempotent'):
                        status.set('同一补丁已应用；本次为幂等重放，修订不变。')
                    if 'extraction' in result:
                        summary = result['extraction']
                        status.set('抽取导入状态 ' + summary['status'] + '；接收 ' + str(summary['accepted']) + ' / 拒收 ' + str(summary['rejected']) + '。候选仍待复核，不代表理解正确。')
        root.after(100, poll)

    def new_import():
        source = filedialog.askopenfilename(title='选择原始审稿材料')
        if not source:
            return
        parent = filedialog.askdirectory(title='选择父目录（将自动创建专用新子目录）')
        if not parent:
            return
        destination = Path(parent) / ('review-' + uuid.uuid4().hex[:12])
        declared = next(value for value, label in origin_labels.items() if label == origin.get())
        kind = source_format.get()
        submit(lambda: controller.import_source(source, destination, declared, kind), '材料已导入。请打开报告复核。')

    def open_existing():
        path = filedialog.askdirectory(title='选择含 review.sqlite3 的工作区')
        if path:
            submit(lambda: controller.open_workspace(path), '已有工作区已打开。')

    def choose_patch():
        if controller.path is None:
            status.set('请先打开已有工作区。')
            return
        path = filedialog.askopenfilename(title='选择下载的草稿补丁', filetypes=[('JSON', '*.json'), ('所有文件', '*')])
        if path:
            submit(lambda: controller.apply_patch(path), '补丁已应用；请重新打开报告查看保存结果。')

    def button(label, action):
        b = ttk.Button(frame, text=label, command=action)
        b.pack(anchor='w', pady=3)
        widgets.append(b)

    attention_location = tk.StringVar(value='尚未打开关注分析；下载草稿不等于已保存。')
    ttk.Label(frame, text='B关注分析', font=('', 14)).pack(anchor='w')
    ttk.Label(frame, textvariable=attention_location, wraplength=700).pack(anchor='w')

    def new_attention():
        if busy:
            return
        from .attention_input_ui import AttentionInputWindow
        AttentionInputWindow(root, controller, on_result=input_result, available=lambda: not busy)

    def input_result(result):
        attention_location.set(str(result['path']) + ' · 已保存修订 ' + str(result['revision']) + ' · ' + result['material_status'])
        status.set('输入已保存。打开关注页整理或核对；建包不表示已经理解B，下载草稿不等于已应用。')

    def choose_attention():
        path = filedialog.askdirectory(title='选择含 attention.sqlite3 的分析包')
        if path:
            submit(lambda: controller.open_attention(path), '关注分析已打开。')

    def migrate_attention():
        from tkinter import simpledialog
        source = filedialog.askopenfilename(title='选择working-attention-index-v1工作稿（原稿保持不变）', filetypes=[('JSON', '*.json')])
        if not source:
            return
        parent = filedialog.askdirectory(title='选择新关注分析包的父目录')
        if not parent:
            return
        actor = simpledialog.askstring('工作稿迁入', '修改者声明')
        if not actor:
            return
        reason = simpledialog.askstring('工作稿迁入', '迁入理由（工作解释不等于已核对）')
        if reason:
            destination = Path(parent) / ('attention-' + uuid.uuid4().hex[:12])
            submit(lambda: controller.migrate_attention(source, destination, actor, reason), '工作稿已迁入新包；请打开关注页核对。')

    def choose_attention_patch():
        patch = filedialog.askopenfilename(title='选择关注草稿补丁', filetypes=[('JSON', '*.json')])
        if patch:
            submit(lambda: controller.apply_attention(patch), '关注补丁已保存，请重开关注页。')

    def choose_attention_a():
        if busy:
            return
        if not getattr(controller, 'attention_path', None):
            status.set('请先打开要接续A版本的关注分析包。')
            return
        from .attention_input_ui import AttentionInputWindow
        AttentionInputWindow(root, controller, a_only=True, on_result=input_result, available=lambda: not busy)

    def choose_attention_a_file():
        source = filedialog.askopenfilename(title='选择A参照清单 attention-a-input/1', filetypes=[('JSON', '*.json')])
        if not source:
            return
        actor = simpledialog.askstring('修改者声明', '谁在导入此A参照？')
        reason = simpledialog.askstring('导入理由', '为何显式导入此版本？')
        if actor and reason:
            submit(lambda: controller.import_attention_a(source, actor, reason), 'A参照已保存；旧版本及绑定保留在历史，请重开核对。')

    button('录入A参照并显式换版', choose_attention_a)
    button('准备A/B输入并建立独立分析', new_attention)
    button('从已有A输入文件导入（高级）', choose_attention_a_file)
    button('迁入B关注工作稿', migrate_attention)
    button('打开关注分析包', choose_attention)
    button('打开关注页', lambda: submit(controller.open_attention_report))
    button('应用关注草稿补丁', choose_attention_patch)
    button('恢复关注页', lambda: submit(controller.recover_attention))
    ttk.Separator(frame).pack(fill='x', pady=8)
    button('新导入（创建专用子目录）', new_import)
    button('打开已有工作区', open_existing)
    button('打开报告', lambda: submit(controller.open_report, '报告已交给本机浏览器打开。'))
    button('选择下载补丁并应用', choose_patch)
    button('恢复报告', lambda: submit(controller.recover, '报告已恢复，请重新打开核对。'))
    ttk.Separator(frame).pack(fill='x', pady=8)
    ttk.Label(frame, text='多来源条款审核包', font=('', 14)).pack(anchor='w')
    ttk.Label(frame, textvariable=batch_location, wraplength=750).pack(anchor='w')

    def choose_batch():
        path = filedialog.askdirectory(title='选择含 batch.sqlite3 的审核包目录')
        if path:
            submit(lambda: controller.open_batch(path), '审核包已恢复；请打开审核页。')

    def choose_batch_decisions():
        path = filedialog.askopenfilename(title='选择下载的审核决定（不是计时记录）', filetypes=[('JSON', '*.json')])
        if path:
            submit(lambda: controller.apply_batch(path), '审核决定已应用保存；请恢复并重开审核页核对。未发布正式标准。')

    def show_refresh_choices(options):
        dialog = tk.Toplevel(root)
        dialog.title('重选授权普通观点并刷新')
        dialog.geometry('780x560')
        dialog.transient(root)
        dialog.grab_set()
        ttk.Label(dialog, text='明确选择后切换为 selected 探索视图；待核不变为已确认。\n仅列原授权普通分区及原运行/手工观点。旧建议不自动转绑新子项，需重新分析。', wraplength=730).pack(padx=12, pady=12)
        canvas = tk.Canvas(dialog)
        scroll = ttk.Scrollbar(dialog, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        content = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        checks = []
        for source in options['sources']:
            ttk.Label(content, text='来源 ' + source['source_id'] + ' · 原视图 ' + source['view']['kind'], wraplength=700).pack(anchor='w', pady=10)
            rows = []
            for candidate in source['choices']:
                enabled = candidate['status'] not in {'rejected', 'withdrawn', 'superseded'}
                value = tk.BooleanVar(value=enabled and candidate['candidate_id'] in source['previous_ids'])
                box = ttk.Checkbutton(content, text=candidate['candidate_id'] + ' · ' + candidate['status'] + ' · ' + candidate['origin'], variable=value)
                box.pack(anchor='w')
                if not enabled:
                    box.configure(state='disabled')
                preview = '\n'.join(e['quote'] for e in candidate['evidence'])
                ttk.Label(content, text=preview + '\n父观点：' + str(candidate.get('parent_ids', [])) +
                    ' · 替换：' + str(candidate.get('replaces', [])), wraplength=700).pack(anchor='w', padx=24)
                rows.append((candidate['candidate_id'], value))
            checks.append((source, rows))

        def confirm_selection():
            selection = {k: options[k] for k in ('batch_id', 'base_revision', 'package_sha256')}
            selection['sources'] = [dict(source_id=s['source_id'], revision=s['revision'],
                candidate_ids=[cid for cid, value in rows if value.get()]) for s, rows in checks]
            dialog.destroy()
            submit(lambda: controller.refresh_batch(selection), '已按所选观点刷新。旧决定需复核；旧建议需重新分析。请重开审核页。')
        ttk.Button(dialog, text='明确选中并刷新（探索视图）', command=confirm_selection).pack(pady=10)

    button('选择审核包', choose_batch)
    button('打开审核页', lambda: submit(controller.open_batch_report, '审核页已交给本机浏览器；下载后仍须应用决定。'))
    button('应用下载决定', choose_batch_decisions)
    def recover_and_reopen():
        result = controller.recover_batch()
        controller.open_batch_report()
        return result
    button('恢复审核包并重开', lambda: submit(recover_and_reopen, '已恢复并打开当前已保存审核页。'))
    button('刷新包（同一观点纠正后）', lambda: submit(controller.refresh_batch, '已刷新绑定；旧决定和旧建议需复核/重新分析。请重开审核页。'))
    button('重选观点并刷新包（拆分/补录后）', lambda: submit(lambda: dict(show_refresh_choices=True, options=controller.batch_refresh_options())))
    search_method = tk.StringVar(value='bge')
    search_box = ttk.Combobox(frame, textvariable=search_method, values=['bge', 'lexical'], state='readonly')
    search_box.pack(anchor='w')
    widgets.append(search_box)
    search_query = tk.StringVar()
    ttk.Label(frame, text='查找普通观点证据（相关性候选，仍需核对原文）').pack(anchor='w')
    search_entry = ttk.Entry(frame, textvariable=search_query, width=65)
    search_entry.pack(anchor='w')
    widgets.append(search_entry)
    def search_batch():
        query = search_query.get()
        if not query.strip():
            status.set('请先输入要查找的普通观点证据。')
            return
        method = search_method.get()
        model = filedialog.askdirectory(title='选择已下载的BGE本地模型目录（不会下载）') if method == 'bge' else None
        if method == 'bge' and not model:
            return
        def search_and_open():
            result = controller.retrieve_batch_text(query, method, model)
            controller.open_batch_report()
            return result
        submit(search_and_open, '本机查找完成；相关性候选已在审核页展示，尚待复核。')
    button('查找所选普通观点证据', search_batch)
    batch_source_box = ttk.Combobox(frame, textvariable=batch_source, state='readonly', width=65)
    batch_source_box.pack(anchor='w')
    widgets.append(batch_source_box)
    button('打开所选原来源（纠正后在上方应用观点补丁）', lambda: submit(lambda: controller.open_batch_source(batch_source.get()), '已切换上方单来源工作区；用原报告纠正并应用观点补丁，再刷新审核包。'))
    ttk.Separator(frame).pack(fill='x', pady=8)
    ttk.Label(frame, text='可选本地模型：仅处理所选普通分区；提取并导入的候选仍待人工复核。').pack(anchor='w')
    section_box = ttk.Combobox(frame, textvariable=section, state='readonly')
    section_box.pack(anchor='w')
    widgets.append(section_box)
    button('显式启动本项目已安装模型', lambda: submit(controller.start_model, '本窗口启动的本地模型已运行。'))
    def extract_selected():
        chosen = section.get()
        submit(lambda: controller.extract(chosen))
    button('抽取所选普通分区并导入', extract_selected)
    def extract_flash():
        plan = filedialog.askopenfilename(title='选择已批准的Flash计划', filetypes=[('JSON', '*.json')])
        if not plan:
            return
        approval = filedialog.askopenfilename(title='选择绑定该计划的批准记录', filetypes=[('JSON', '*.json')])
        if not approval:
            return
        alias = simpledialog.askstring('获准Flash', '输入已批准的单项alias：', parent=root)
        if alias:
            chosen = section.get()
            submit(lambda: controller.extract_approved(plan, approval, alias, chosen))
    button('获准Flash抽取所选普通分区并导入', extract_flash)
    button('停止本窗口启动的模型', lambda: submit(controller.stop_model, '本窗口启动的模型已停止。'))

    def close():
        if busy:
            status.set('当前操作尚未结束；请等待完成后关闭，避免中断保存。')
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    poll()
    root.mainloop()
    return 0
