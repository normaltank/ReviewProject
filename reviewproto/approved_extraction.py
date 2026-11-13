"""Explicit approved Flash orchestration using the existing DPAPI launcher."""
from contextlib import closing
from pathlib import Path
import re

from .batch import checked_local
from .core import ReviewError, require
from .store import Workspace


def preflight(workspace, plan, approval, alias, section, run_id):
    from experiments import deepseek_trial as trial
    try:
        return trial.preflight(checked_local(plan), checked_local(approval), alias, run_id,
                               workspace=checked_local(workspace), section_id=section)
    except ValueError as error:
        code = str(error)
        raise ReviewError(code if re.fullmatch(r'E_[A-Z_]+', code) else 'E_APPROVED_PREFLIGHT') from None


def execute(workspace, plan, approval, alias, section, run_id, *, transport=None, key_getter=None):
    """Called inside the safe launcher, or with explicit injected test seams."""
    from experiments import deepseek_trial as trial
    preflight(workspace, plan, approval, alias, section, run_id)
    trial.run(plan, approval, alias, run_id, transport=transport, key_getter=key_getter)
    payload = Path(workspace) / 'model-artifacts' / run_id / 'candidates.json'
    with closing(Workspace(workspace)) as ws:
        ws.import_extractions(input_path=payload)
        return ws.last_import_summary


def launch(workspace, plan, approval, alias, section, run_id, *, check_only=False, process=None):
    # Validation occurs in the same optional model environment as the existing
    # launcher. The core Python environment need not install LangExtract.
    from .desktop import ROOT, run_powershell
    require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id), 'E_RUN_ID')
    workspace, plan, approval = map(checked_local, (workspace, plan, approval))
    require((workspace / 'review.sqlite3').is_file(), 'E_WORKSPACE_MISSING')
    from experiments import deepseek_trial as trial
    try:
        checked = trial.validate_plan(plan, approval, alias)
    except ValueError as error:
        code = str(error)
        raise ReviewError(code if re.fullmatch(r'E_[A-Z_]+', code) else 'E_APPROVED_PREFLIGHT') from None
    require(checked[3] == workspace, 'E_PLAN_WORKSPACE_MISMATCH')
    require(checked[1]['section_id'] == section, 'E_SECTION_SELECTION')
    from .batch import source_state
    require(not any(r['run_id'] == run_id for r in source_state(workspace).get('extraction_runs', [])), 'E_RUN_EXISTS')
    args = ['-ExecutionPolicy', 'Bypass', '-File', ROOT / 'scripts/run-deepseek-trial.ps1',
            '-Plan', plan, '-Approval', approval, '-Item', alias, '-RunId', run_id,
            '-Workspace', workspace, '-Section', section]
    if check_only:
        args.append('-CheckOnly')
    result = (process or run_powershell)(args)
    if check_only:
        require(result.returncode == 0, 'E_APPROVED_PREFLIGHT')
        return dict(status='checked')
    # A failed/partial producer must still leave an imported audit; the exit
    # code alone never proves a complete extraction.
    with closing(Workspace(workspace)) as ws:
        state = ws.state()
        run = next((r for r in state['extraction_runs'] if r['run_id'] == run_id), None)
        require(run is not None, 'E_APPROVED_EXTRACTION_FAILED')
        require(run['config'].get('plan_sha256') == checked[4] and run['config'].get('alias') == alias,
                'E_APPROVED_EXTRACTION_FAILED')
        return dict(status=run['status'], accepted=len(run.get('accepted_ids', [])), rejected=len(run.get('rejected', [])))
