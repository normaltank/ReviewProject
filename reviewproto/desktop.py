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
    if code in {'E_REVISION_CONFLICT', 'E_PATCH_REVISION'}:
        return code + '：补丁修订已过期。请重新打开报告，重新导出修改；不会自动改写修订号。'
    if code == 'E_OUTPUT_FAILED':
        return code + '：修改已提交，但报告输出失败。请使用“恢复报告”，再重新打开核对；不要改写补丁修订号。'
    if code.startswith('E_LOCAL_MODEL') or code == 'E_MODEL_NOT_OWNED':
        return code + '：请核对本机已安装模型与项目服务状态。不会下载或接管其他实例；启动失败的实例请由原启动窗口或项目脚本核对停止。'
    return code + '：操作未完成；保存可能已提交。请保留所选文件，使用“恢复报告”核对当前修订后重试。'


def run_process(argv):
    return subprocess.run([str(v) for v in argv], cwd=ROOT, shell=False, capture_output=True,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)


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
        from tkinter import filedialog, ttk
    except ImportError:
        raise ReviewError('E_DESKTOP_UNAVAILABLE') from None

    root = tk.Tk()
    root.title('ReviewProject · 可信编辑本机入口')
    root.geometry('760x720')
    controller, results = Controller(), queue.Queue()
    busy = False
    widgets = []
    status = tk.StringVar(value='选择新材料或已有工作区。材料、报告和补丁仅供可信编辑。')
    location = tk.StringVar(value='尚未打开工作区')
    origin_labels = {'unknown': '未确认', 'original_review': '原始审稿', 'synthetic': '合成演示'}
    origin = tk.StringVar(value=origin_labels['unknown'])
    source_format = tk.StringVar(value='docx')
    section = tk.StringVar()
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill='both', expand=True)
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
                if isinstance(result, dict):
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

    button('新导入（创建专用子目录）', new_import)
    button('打开已有工作区', open_existing)
    button('打开报告', lambda: submit(controller.open_report, '报告已交给本机浏览器打开。'))
    button('选择下载补丁并应用', choose_patch)
    button('恢复报告', lambda: submit(controller.recover, '报告已恢复，请重新打开核对。'))
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
    button('停止本窗口启动的模型', lambda: submit(controller.stop_model, '本窗口启动的模型已停止。'))
    ttk.Label(frame, textvariable=status, wraplength=700).pack(anchor='w', pady=12)

    def close():
        if busy:
            status.set('当前操作尚未结束；请等待完成后关闭，避免中断保存。')
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    poll()
    root.mainloop()
    return 0
