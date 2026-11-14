"""Ordinary input preparation; source snapshots stay separate from A versions."""
from __future__ import annotations

import copy
import uuid
import tempfile
from contextlib import closing
from pathlib import Path

from .attention import AttentionWorkspace
from .attention_a import validate_reference
from .batch import bounded, checked_local, source_state
from .core import require
from .store import encoded


def nonempty(value):
    require(isinstance(value, str) and bool(value.strip()), 'E_ATTENTION_TEXT')
    return value


class AttentionInput:
    """An editable checklist, containing only explicitly selected ordinary input."""

    def __init__(self):
        self.records = []
        self.a_reference = {'version': 'no-a', 'parts': [], 'items': []}
        self.workspace_checks = {}

    @staticmethod
    def workspace_options(path):
        state = source_state(path)
        return [copy.deepcopy(s) for s in state['sections']
                if s['visibility'] in {'author_visible', 'visibility_unknown'}]

    def add_workspace(self, path, section_id, paper_id=''):
        path = checked_local(path)
        state = source_state(path)
        selected = next((s for s in state['sections'] if s['section_id'] == section_id), None)
        require(selected is not None, 'E_ATTENTION_SECTION')
        require(selected['visibility'] in {'author_visible', 'visibility_unknown'}, 'E_ATTENTION_PRIVATE')
        check = (state['revision'], state['source']['source_id'])
        if any(r.get('workspace') == str(path) for r in self.records):
            require(self.workspace_checks.get(str(path)) == check, 'E_ATTENTION_REVALIDATION')
        self.workspace_checks[str(path)] = check
        record = dict(kind='workspace', workspace=str(path), section_id=section_id)
        if paper_id:
            record['paper_id'] = nonempty(paper_id)
        self.records.append(record)
        return len(self.records) - 1

    def remove(self, index):
        del self.records[index]

    def replace_transcription(self, index, *args, **kwargs):
        self.add_transcription(*args, **kwargs)
        self.records[index] = self.records.pop()

    def add_transcription(self, anchor, text, visibility, scores=(), locator='', paper_id=''):
        require(visibility in {'author_visible', 'visibility_unknown'}, 'E_ATTENTION_PRIVATE')
        require(isinstance(scores, (list, tuple)) and all(isinstance(s, dict) and
                set(s) == {'label', 'raw_value'} and all(isinstance(v, str) for v in s.values())
                for s in scores), 'E_ATTENTION_SCORES')
        record = dict(kind='transcription', anchor=nonempty(anchor), text=nonempty(text),
                      visibility=visibility, scores=copy.deepcopy(list(scores)),
                      locator={'transcription_anchor': anchor, 'description': nonempty(locator)})
        if paper_id:
            record['paper_id'] = nonempty(paper_id)
        self.records.append(record)
        return len(self.records) - 1

    def set_a(self, reference):
        validate_reference(reference)
        self.a_reference = copy.deepcopy(reference)


def prepared_payload(draft):
    require(isinstance(draft, AttentionInput), 'E_ATTENTION_SCHEMA')
    require(bool(draft.records), 'E_ATTENTION_EMPTY')
    validate_reference(draft.a_reference)
    require(bool(draft.a_reference['items']) or not draft.a_reference.get('parts'), 'E_ATTENTION_A')
    for record in draft.records:
        if record.get('kind') == 'workspace':
            state = source_state(record['workspace'])
            require(draft.workspace_checks.get(record['workspace']) ==
                    (state['revision'], state['source']['source_id']), 'E_ATTENTION_REVALIDATION')
    absent_version = 'no-a'
    if draft.a_reference['items'] and draft.a_reference['version'] == absent_version:
        absent_version += '-' + uuid.uuid4().hex
    return bounded({'schema': 'attention-input/1', 'records': copy.deepcopy(draft.records),
                    'a_reference': {'version': absent_version, 'parts': [], 'items': []}})


def validate_prepared(draft, destination):
    payload = prepared_payload(draft)
    destination = checked_local(destination)
    require(not destination.exists() or destination.is_dir() and not any(destination.iterdir()),
            'E_ATTENTION_NOT_DEDICATED')
    # Run the actual engine's entire input validation before touching the chosen
    # location. A disposable package also exercises duplicate/source/size guards.
    # Keep derived text inside the selected output's local permission boundary,
    # rather than putting a real input copy in the system-wide temp location.
    existing_parent = next(parent for parent in destination.parents if parent.is_dir())
    with tempfile.TemporaryDirectory(prefix='.attention-input-check-', dir=existing_parent) as folder:
        with closing(AttentionWorkspace(Path(folder) / 'check')) as ws:
            ws.build(payload)
            if draft.a_reference['items']:
                import_prepared_a(ws, draft.a_reference, '本机输入', '建包前整份清单预检')
    return payload, destination


def build_prepared(draft, destination, on_committed=None):
    payload, destination = validate_prepared(draft, destination)
    ws = AttentionWorkspace(destination)
    try:
        inputs = destination / 'inputs'
        inputs.mkdir()
        b_path = inputs / 'b-input.json'
        with b_path.open('xb') as stream:
            stream.write(encoded(payload))
        state = ws.build(input_path=b_path)
        if draft.a_reference['items']:
            state = import_prepared_a(ws, draft.a_reference, '本机输入', '建立分析时显式采用A版本')
        if on_committed:
            on_committed(destination)
        return state
    except Exception:
        # A render failure can follow a commit. Preserve that recoverable target,
        # while an input rejection must not replace the current open context.
        try:
            ws.state()
        except Exception:
            pass
        else:
            if on_committed:
                on_committed(destination)
        raise
    finally:
        ws.close()


def import_prepared_a(ws, reference, actor, reason):
    validate_reference(reference)
    require(bool(reference['items']), 'E_ATTENTION_A_VERSION')
    nonempty(actor); nonempty(reason)
    payload = bounded({'schema': 'attention-a-input/1', 'a_reference': copy.deepcopy(reference)})
    inputs = checked_local(ws.path / 'inputs')
    inputs.mkdir(exist_ok=True)
    path = checked_local(inputs / ('a-' + uuid.uuid4().hex + '.json'))
    with path.open('xb') as stream:
        stream.write(encoded(payload))
    return ws.import_a(path, actor=actor, reason=reason)
