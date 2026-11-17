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
        self.attention_path = None
        self._sessions = {}

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

    def import_attention_a(self, source, actor, reason):
        from .attention import AttentionWorkspace
        require(getattr(self, 'attention_path', None) is not None, 'E_ATTENTION_EMPTY')
        ws = AttentionWorkspace(self.attention_path)
        try:
            return self._attention_result(ws.import_a(source, actor=actor, reason=reason))
        finally:
            ws.close()

    def attention_session(self, path=None):
        from .attention_server import AttentionSession
        path = Path(path or self.attention_path).resolve()
        if path not in self._sessions:
            self._sessions[path] = AttentionSession(path)
        return self._sessions[path]

    def open_attention_report(self, path=None):
        import webbrowser
        session = self.attention_session(path)
        require(webbrowser.open(session.url), 'E_BROWSER_OPEN')
        from .attention import AttentionWorkspace
        with closing(AttentionWorkspace(session._path)) as ws:
            state = ws.state()
        return dict(kind='attention', path=session._path, revision=state['revision'], material_status=state['material_status'])

    def close(self):
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()


def main():
    try:
        import tkinter as tk
        from tkinter import filedialog, ttk
    except ImportError:
        raise ReviewError('E_DESKTOP_UNAVAILABLE') from None
    root = tk.Tk()
    root.title('ReviewProject · 评语分析')
    root.geometry('800x540')
    controller = Controller()
    candidate_windows = []
    status = tk.StringVar(value='新建分析，录入评语；或打开已有分析继续。')
    location = tk.StringVar(value='尚未打开分析')
    frame = ttk.Frame(root, padding=24); frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='评语分析', font=('',18)).pack(anchor='w', pady=(0,16))
    ttk.Label(frame,textvariable=status,wraplength=720).pack(fill='x')
    ttk.Label(frame,textvariable=location,wraplength=720).pack(fill='x',pady=16)
    def result(value):
        location.set(str(value['path'])+' · 已保存修订 '+str(value['revision']))
        actions.pack(fill='x',pady=16)
        status.set('输入已保存。分析评语，或查看并修改已有结果。')
    def perform(action):
        try:
            value=action()
            if isinstance(value,dict): result(value)
        except Exception as exc: status.set(safe_message(exc))
    def new_analysis():
        from .attention_input_ui import AttentionInputWindow
        AttentionInputWindow(root,controller,on_result=result)
    def open_analysis():
        path=filedialog.askdirectory(title='打开分析包（attention.sqlite3所在目录）')
        if path: perform(lambda:controller.open_attention(path))
    def analyze():
        from .attention_candidate_ui import AttentionCandidateWindow
        perform(lambda:candidate_windows.append(AttentionCandidateWindow(root,controller,on_result=result)))
    def change_a():
        from .attention_input_ui import AttentionInputWindow
        AttentionInputWindow(root,controller,a_only=True,on_result=result)
    ttk.Button(frame,text='新建分析',command=new_analysis).pack(anchor='w',pady=4)
    ttk.Button(frame,text='打开已有分析',command=open_analysis).pack(anchor='w',pady=4)
    actions=ttk.Frame(frame)
    ttk.Button(actions,text='分析评语',command=analyze).pack(anchor='w',pady=4)
    ttk.Button(actions,text='查看并修改结果',command=lambda:perform(controller.open_attention_report)).pack(anchor='w',pady=4)
    ttk.Button(actions,text='修改A参照（可选）',command=change_a).pack(anchor='w',pady=4)
    def close():
        if any(w.window.winfo_exists() and (w.busy or w.service.owned) for w in candidate_windows):
            status.set('请等待分析结束，并在分析设置中停止本窗口启动的模型，再关闭。');return
        controller.close();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    root.mainloop()
    return 0
