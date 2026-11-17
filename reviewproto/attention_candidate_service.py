"""Ordinary, target-bound local candidate workflow. No SQLite crosses threads."""
from contextlib import closing
from pathlib import Path
import copy
import json
import re

from .attention import AttentionWorkspace
from .attention_candidates import generate, preview, accept
from .attention_candidate_render import render_candidate_preview
from .local_model_profiles import profile, DEFAULT_MODEL
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
        return '尚未配置DeepSeek。请展开网页“分析设置”保存密钥。'
    if code == 'E_DEEPSEEK_CREDENTIAL_STORE':
        return 'API凭据无法保存或解密。请使用当前Windows用户重新保存，或显式设置DEEPSEEK_API_KEY。'
    if code == 'E_ATTENTION_API_MODEL':
        return 'API仅支持用户指定的DeepSeek 4.1 Flash / 1017，请选择deepseek-flash；不会改用Pro。'
    if code.startswith('E_ATTENTION_API'):
        return 'DeepSeek API操作未完成。请核对官方地址、模型和凭据；不会自动重试或改用本机模型。'
    if code == 'E_LOCAL_MODEL_MISSING':
        return '所选模型未安装。请由操作员按候选分析操作说明，将对应 GGUF 文件放入资源根目录的 .tools/local-llm 后重试；工作台不会下载。'
    if code == 'E_LOCAL_MODEL_WEIGHT':
        return '所选模型大小或 SHA-256 不符。请由操作员按候选分析操作说明核对固定文件版本并重新安装。'
    if code == 'E_ATTENTION_MODEL_PROFILE':
        return '模型名称不在已支持的固定配置中。请从模型下拉列表选择。'
    if code == 'E_ATTENTION_CAPACITY_PROFILE':
        return '表达分类需要至少768的输出长度以保留有界思考和完整结果。请将最大输出长度设为至少768后重新生成；本次未提高你设置的上限。'
    if code == 'E_ATTENTION_TARGET':
        return '目标或保存修订已变化。请刷新当前分析包并重新打开；原候选仍保留在原包。'
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


