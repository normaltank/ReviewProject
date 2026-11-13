"""Independent local attention analysis. SQLite commits precede recoverable views."""
from __future__ import annotations
import copy
import json
import sqlite3
import uuid
from pathlib import Path
from .core import ReviewError, digest, require
from .store import atomic, encoded, now, PRIVATE_IGNORE, read_input
from .framework import load_json
from .batch import bounded, checked_local, read_json, source_state

SCHEMA = 'attention/1'


def _text(value):
    require(isinstance(value, str) and bool(value.strip()), 'E_ATTENTION_TEXT')
    return value


def _records(payload, base):
    records, bindings = [], []
    for item in payload['records']:
        if item.get('kind') == 'workspace':
            path = checked_local(base / item['workspace'])
            source = source_state(path)
            selected = [s for s in source['sections'] if s['section_id'] == item['section_id']]
            require(len(selected) == 1, 'E_ATTENTION_SECTION')
            section = selected[0]
            require(section['visibility'] in {'author_visible', 'visibility_unknown'}, 'E_ATTENTION_PRIVATE')
            record = {'anchor': item['section_id'], 'text': section['text'], 'visibility': section['visibility'], 'scores': source['scores'], 'locator': section['locator'], 'kind': 'workspace', 'source_id': source['source']['source_id']}
            binding = {'kind': 'workspace', 'path': str(path), 'section_id': item['section_id'], 'revision': source['revision'], 'source_id': source['source']['source_id'], 'fingerprint': digest(encoded(record))}
        else:
            require(item.get('kind', 'transcription') == 'transcription', 'E_ATTENTION_SOURCE')
            require(item.get('visibility') == 'author_visible', 'E_ATTENTION_PRIVATE')
            record = {'anchor': _text(item['anchor']), 'text': _text(item['text']), 'scores': item.get('scores', []), 'visibility': 'author_visible', 'locator': item.get('locator', {'transcription_anchor': item['anchor']}), 'kind': 'transcription'}
            record['source_id'] = digest(encoded(record))
            binding = None
        require(isinstance(record['scores'], list), 'E_ATTENTION_SCORES')
        for score in record['scores']:
            require(isinstance(score, dict) and isinstance(score.get('label'), str) and isinstance(score.get('raw_value'), str), 'E_ATTENTION_SCORES')
        record['record_id'] = 'r-' + digest(encoded([record['kind'], record['source_id']]))[:32]
        record['sections'] = [{'section_id': record['anchor'], 'text': record['text'], 'locator': record['locator']}]
        if record['kind'] == 'workspace' and any(r['record_id'] == record['record_id'] for r in records):
            previous = next(r for r in records if r['record_id'] == record['record_id'])
            require(record['anchor'] not in {s['section_id'] for s in previous['sections']}, 'E_ATTENTION_DUPLICATE')
            previous['sections'].extend(record['sections'])
            bindings.append(binding)
            continue
        require(record['record_id'] not in {r['record_id'] for r in records}, 'E_ATTENTION_DUPLICATE')
        records.append(record)
        if binding:
            bindings.append(binding)
    require(records, 'E_ATTENTION_EMPTY')
    return records, bindings


class AttentionWorkspace:
    APPLICATION_ID = 0x4154544E

    def __init__(self, path):
        self.path = checked_local(path)
        require(not self.path.exists() or self.path.is_dir(), 'E_ATTENTION_DIRECTORY')
        if self.path.exists() and not (self.path / 'attention.sqlite3').exists():
            require(not any(self.path.iterdir()), 'E_ATTENTION_NOT_DEDICATED')
        self.path.mkdir(parents=True, exist_ok=True)
        for name in ('attention.sqlite3', 'attention.sqlite3-wal', 'attention.sqlite3-shm', 'attention.html', 'attention-state.json', '.gitignore'):
            checked_local(self.path / name)
        self.db = sqlite3.connect(self.path / 'attention.sqlite3')
        app = self.db.execute('PRAGMA application_id').fetchone()[0]
        require(app == self.APPLICATION_ID or app == 0 and not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone(), 'E_ATTENTION_DATABASE')
        self.db.execute('PRAGMA application_id=' + str(self.APPLICATION_ID))
        self.db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS history(revision INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, payload TEXT NOT NULL)')
        self.db.commit()
        atomic(self.path / '.gitignore', PRIVATE_IGNORE)

    def close(self):
        self.db.close()

    def state(self):
        row = self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        require(row is not None, 'E_ATTENTION_EMPTY')
        state = json.loads(row[0])
        require(state['schema'] == SCHEMA, 'E_ATTENTION_SCHEMA')
        state['material_status'] = 'current'
        for binding in state['bindings']:
            try:
                if binding['kind'] == 'file':
                    unchanged = digest(checked_local(binding['path']).read_bytes()) == binding['fingerprint']
                else:
                    source = source_state(binding['path'])
                    unchanged = source['revision'] == binding['revision'] and source['source']['source_id'] == binding['source_id']
                if not unchanged:
                    state['material_status'] = 'needs_revalidation'
            except Exception:
                state['material_status'] = 'needs_revalidation'
        state['history'] = [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM history ORDER BY revision')]
        return state

    def build(self, payload=None, *, base=None, input_path=None):
        require(self.db.execute('SELECT 1 FROM state').fetchone() is None, 'E_ATTENTION_EXISTS')
        if input_path:
            input_path = checked_local(input_path)
            input_bytes = read_input(input_path, 10_000_000, 'E_ATTENTION_LIMIT')
            payload, base = load_json(input_bytes), input_path.parent
        require(isinstance(payload, dict) and payload.get('schema') == 'attention-input/1', 'E_ATTENTION_SCHEMA')
        require(isinstance(payload.get('records'), list), 'E_ATTENTION_SOURCE')
        records, bindings = _records(payload, Path(base or '.'))
        a = payload.get('a_reference')
        require(isinstance(a, dict) and isinstance(a.get('items'), list), 'E_ATTENTION_A')
        _text(a.get('version'))
        ids = set()
        for item in a['items']:
            for key in ('id', 'text', 'locator'):
                _text(item.get(key))
            require(item['id'] not in ids, 'E_ATTENTION_A')
            ids.add(item['id'])
        if input_path:
            bindings.append({'kind': 'file', 'path': str(input_path), 'fingerprint': digest(input_bytes)})
        state = {'schema': SCHEMA, 'analysis_id': str(uuid.uuid4()), 'revision': 0, 'records': records, 'bindings': bindings, 'a_reference': copy.deepcopy(a), 'input_fingerprint': digest(encoded(payload)), 'rules_version': 'manual-evidence/1', 'opinions': [], 'themes': [], 'relations': []}
        bounded(state)
        with self.db:
            self.db.execute('INSERT INTO state VALUES(1,?)', (encoded(state).decode(),))
        return self.recover()

    def apply(self, patch=None, *, input_path=None):
        if input_path:
            patch = read_json(input_path)
        fingerprint = digest(encoded(patch))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute('SELECT 1 FROM history WHERE fingerprint=?', (fingerprint,)).fetchone()
            if not existing:
                state = self.state()
                require(state['material_status'] == 'current', 'E_ATTENTION_REVALIDATION')
                require(patch.get('schema') == 'attention-patch/1' and patch.get('analysis_id') == state['analysis_id'], 'E_ATTENTION_PATCH')
                require(type(patch.get('base_revision')) is int and patch['base_revision'] == state['revision'], 'E_ATTENTION_CONFLICT')
                _text(patch.get('actor')); _text(patch.get('reason'))
                require(isinstance(patch.get('edits'), list) and patch['edits'], 'E_ATTENTION_PATCH')
                seen = set()
                for edit in patch['edits']:
                    require(set(edit) <= {'opinion_id', 'facet_id', 'record_id', 'evidence', 'interpretation', 'status'}, 'E_ATTENTION_PATCH')
                    oid = _text(edit.get('opinion_id')); fid = _text(edit.get('facet_id'))
                    require(oid not in seen, 'E_ATTENTION_DUPLICATE'); seen.add(oid)
                    record = next((r for r in state['records'] if r['record_id'] == edit.get('record_id')), None)
                    require(record is not None, 'E_ATTENTION_RECORD')
                    require(isinstance(edit.get('evidence'), list) and edit['evidence'], 'E_ATTENTION_EVIDENCE')
                    for ev in edit['evidence']:
                        require(isinstance(ev, dict) and set(ev) == {'source_id', 'section_id', 'start', 'end', 'quote'}, 'E_ATTENTION_EVIDENCE')
                        section = next((s for s in record['sections'] if s['section_id'] == ev['section_id']), None)
                        require(section is not None, 'E_ATTENTION_SECTION')
                        require(type(ev['start']) is int and type(ev['end']) is int and 0 <= ev['start'] < ev['end'] <= len(section['text']), 'E_ATTENTION_RANGE')
                        require(ev['source_id'] == record['source_id'] and section['text'][ev['start']:ev['end']] == ev['quote'], 'E_ATTENTION_QUOTE')
                    _text(edit.get('interpretation'))
                    require(edit.get('status') in {'working', 'needs_review', 'confirmed', 'withdrawn'}, 'E_ATTENTION_STATUS')
                    previous = next((o for o in state['opinions'] if o['opinion_id'] == oid), None)
                    if previous:
                        require(previous['record_id'] == edit['record_id'] and previous['facet_id'] == fid, 'E_ATTENTION_IDENTITY')
                        previous.update(copy.deepcopy(edit))
                    else:
                        require(not any(o['facet_id'] == fid for o in state['opinions']), 'E_ATTENTION_IDENTITY')
                        state['opinions'].append(dict(copy.deepcopy(edit), replaces=[], themes=[], a_links=[], outside=[], expression={'function': '', 'boilerplate_candidate': None}, qualifiers={'object': '', 'direction': '', 'degree': '', 'negation': '', 'reasons': [], 'conditions': [], 'actions': []}))
                bounded(state)
                state['revision'] += 1
                audit = {'revision': state['revision'], 'actor': patch['actor'], 'reason': patch['reason'], 'at': now(), 'fingerprint': fingerprint, 'patch': patch}
                self.db.execute('INSERT INTO history VALUES(?,?,?)', (state['revision'], fingerprint, encoded(audit).decode()))
                state.pop('history', None); state.pop('material_status', None)
                self.db.execute('UPDATE state SET payload=? WHERE id=1', (encoded(state).decode(),))
        return self.recover()

    def recover(self):
        from .attention_render import render
        state = self.state()
        try:
            atomic(checked_local(self.path / 'attention-state.json'), encoded(state))
            atomic(checked_local(self.path / 'attention.html'), render(state).encode('utf-8'))
        except Exception:
            raise ReviewError('E_ATTENTION_OUTPUT_RECOVER') from None
        return state
