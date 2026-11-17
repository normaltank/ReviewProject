"""Small local launcher; Tk and model dependencies are loaded only on demand."""
from contextlib import closing
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

from .core import ReviewError, require

ROOT = Path(__file__).resolve().parents[1]
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
    if code.startswith('E_LOCAL_MODEL') or code == 'E_MODEL_NOT_OWNED':
        return code + '：请核对本机已安装模型与项目服务状态。不会下载或接管其他实例；启动失败的实例请由原启动窗口或项目脚本核对停止。'
    return code + '：操作未完成，请保留当前材料并重新打开分析核对。'


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
        from .local_io import checked_local
        require(path is not None or self.attention_path is not None, 'E_ATTENTION_EMPTY')
        path = checked_local(path or self.attention_path)
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


class DesktopWindow:
    """Current material and its next action, with maintenance a level deeper."""
    def __init__(self, root, controller):
        import tkinter as tk
        from tkinter import ttk
        from .native_ui import theme, wrapped
        self.root, self.controller = root, controller
        self.candidate_windows = []
        theme(root)
        root.title('ReviewProject · 评语分析')
        root.geometry('920x650'); root.minsize(700, 540)
        self.status = tk.StringVar(value='从一批评语开始。原话先保存，分析后再核对。')
        self.location = tk.StringVar(value='尚未打开分析')
        frame = ttk.Frame(root, padding=28); frame.pack(fill='both', expand=True)
        header = ttk.Frame(frame); header.pack(fill='x')
        ttk.Label(header, text='评语分析', style='Title.TLabel').pack(side='left')
        self.new_button = ttk.Button(header, text='新建分析', command=self.new_analysis, style='Primary.TButton')
        self.new_button.pack(side='right')
        ttk.Button(header, text='打开已有分析', command=self.open_analysis).pack(side='right', padx=10)
        ttk.Separator(frame).pack(fill='x', pady=(22, 28))
        self.heading = ttk.Label(frame, text='准备本批材料', style='Heading.TLabel')
        self.heading.pack(anchor='w')
        wrapped(frame, textvariable=self.status, style='TLabel').pack(fill='x', pady=(12, 18))
        self.actions = ttk.Frame(frame); self.actions.pack(fill='x')
        self.analyze_button = ttk.Button(self.actions, text='分析评语', command=self.analyze, style='Primary.TButton')
        self.view_button = ttk.Button(self.actions, text='查看并修改结果', command=lambda: self.perform(controller.open_attention_report))
        self.materials_button = ttk.Button(self.actions, text='材料与恢复…', command=self.toggle_materials)
        self.details = ttk.Frame(frame, padding=(0, 18))
        wrapped(self.details, textvariable=self.location).pack(fill='x', pady=(0, 12))
        self.change_a_button = ttk.Button(self.details, text='修改A参照（可选）', command=self.change_a)
        self.recover_button = ttk.Button(self.details, text='恢复关注页', command=lambda: self.perform(controller.recover_attention))
        spacer = ttk.Frame(frame); spacer.pack(fill='both', expand=True)
        ttk.Separator(frame).pack(fill='x', pady=(18, 12))
        wrapped(frame, text='原话、原分和分析保存在本机。A关注方向可稍后添加。').pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)

    def result(self, value):
        self.location.set(str(value['path']) + ' · 已保存修订 ' + str(value['revision']))
        self.heading.configure(text='继续这批评语')
        self.new_button.configure(style='TButton')
        self.status.set('已保存修订 ' + str(value['revision']) + '。开始分析评语，或继续阅读和修改结果。' if value.get('material_status') != 'needs_revalidation'
                        else '来源或A参照需要核对。旧快照已保留，请展开材料与恢复检查。')
        self.analyze_button.pack(side='left')
        self.view_button.pack(side='left', padx=10)
        self.materials_button.pack(side='right')

    def toggle_materials(self):
        if self.change_a_button.winfo_manager():
            self.change_a_button.pack_forget(); self.recover_button.pack_forget(); self.details.pack_forget()
            self.materials_button.configure(text='材料与恢复…')
        else:
            self.details.pack(fill='x', after=self.actions)
            self.change_a_button.pack(side='left'); self.recover_button.pack(side='left', padx=10)
            self.materials_button.configure(text='收起材料与恢复')

    def perform(self, action):
        try:
            value = action()
            if isinstance(value, dict): self.result(value)
        except Exception as exc:
            self.status.set(safe_message(exc))

    def new_analysis(self):
        from .attention_input_ui import AttentionInputWindow
        AttentionInputWindow(self.root, self.controller, on_result=self.result)

    def open_analysis(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(parent=self.root, title='打开已有分析（选择分析所在目录）')
        if path: self.perform(lambda: self.controller.open_attention(path))

    def analyze(self):
        from .attention_candidate_ui import AttentionCandidateWindow
        self.perform(lambda: self.candidate_windows.append(AttentionCandidateWindow(self.root, self.controller, on_result=self.result)))

    def change_a(self):
        from .attention_input_ui import AttentionInputWindow
        AttentionInputWindow(self.root, self.controller, a_only=True, on_result=self.result)

    def close(self):
        if any(w.window.winfo_exists() and (w.busy or w.service.owned) for w in self.candidate_windows):
            self.status.set('请等待分析结束，并在分析设置中停止本窗口启动的模型，再关闭。')
            return
        self.controller.close(); self.root.destroy()


def main():
    try:
        import tkinter as tk
    except ImportError:
        raise ReviewError('E_DESKTOP_UNAVAILABLE') from None
    root = tk.Tk()
    DesktopWindow(root, Controller())
    root.mainloop()
    return 0
