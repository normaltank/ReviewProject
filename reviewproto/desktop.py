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


def main(argv=None):
    """Compatibility entry; all interaction now takes place in the browser."""
    from .workbench_launcher import main as launch
    return launch([] if argv is None else argv)
