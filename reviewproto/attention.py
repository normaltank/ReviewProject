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
            require(item.get('visibility') in {'author_visible', 'visibility_unknown'}, 'E_ATTENTION_PRIVATE')
            record = {'anchor': _text(item['anchor']), 'text': _text(item['text']), 'scores': item.get('scores', []), 'visibility': item['visibility'], 'locator': item.get('locator', {'transcription_anchor': item['anchor']}), 'kind': 'transcription'}
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
        from .attention_model import upgrade
        upgrade(state)
        state['material_status'] = 'current'
        state['b_material_status'] = 'current'
        state['a_material_status'] = 'current'
        for binding in state['bindings']:
            try:
                if binding['kind'] == 'file':
                    unchanged = digest(checked_local(binding['path']).read_bytes()) == binding['fingerprint']
                else:
                    source = source_state(binding['path'])
                    unchanged = source['revision'] == binding['revision'] and source['source']['source_id'] == binding['source_id']
            except Exception:
                unchanged = False
            if not unchanged:
                state['material_status'] = 'needs_revalidation'
                state['a_material_status' if binding.get('role') == 'a_reference' else 'b_material_status'] = 'needs_revalidation'
        if state['a_material_status'] != 'current':
            from .attention_model import project
            for op in state['opinions']:
                for facet in op['facets']:
                    for link in facet['a_links']:
                        if link['status'] != 'withdrawn': link['status'] = 'needs_review'
                project(op)
        state['history'] = [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM history ORDER BY revision')]
        return state

    def build(self, payload=None, *, base=None, input_path=None, _working=None):
        require(self.db.execute('SELECT 1 FROM state').fetchone() is None, 'E_ATTENTION_EXISTS')
        if input_path:
            input_path = checked_local(input_path)
            input_bytes = read_input(input_path, 10_000_000, 'E_ATTENTION_LIMIT')
            payload, base = load_json(input_bytes), input_path.parent
        require(isinstance(payload, dict) and payload.get('schema') == 'attention-input/1', 'E_ATTENTION_SCHEMA')
        require(isinstance(payload.get('records'), list), 'E_ATTENTION_SOURCE')
        records, bindings = _records(payload, Path(base or '.'))
        a = payload.get('a_reference')
        from .attention_a import validate_reference
        validate_reference(a)
        if input_path:
            bindings.append({'kind': 'file', 'path': str(input_path), 'fingerprint': digest(input_bytes)})
        state = {'schema': SCHEMA, 'analysis_id': str(uuid.uuid4()), 'revision': 0, 'records': records, 'bindings': bindings, 'a_reference': copy.deepcopy(a), 'input_fingerprint': digest(encoded(payload)), 'rules_version': 'manual-evidence/1', 'opinions': [], 'themes': [], 'relations': []}
        audit = None
        if _working:
            from .attention_draft import objects
            from .attention_model import apply_objects
            draft, themes, aliases, lookup, binding, actor, reason = _working
            state['bindings'].append(binding)
            patch = dict(objects(draft, state, themes, aliases, lookup), schema='attention-patch/2', analysis_id=state['analysis_id'], base_revision=0, actor=actor, reason=reason)
            apply_objects(state, patch)
            state['revision'] = 1
            state['migration'] = {'adapter': 'working-attention-index-v1', 'fingerprint': binding['fingerprint'], 'status': 'working_not_gold'}
            audit = {'revision': 1, 'actor': actor, 'reason': reason, 'at': now(), 'fingerprint': digest(encoded(patch)), 'patch': patch}
        bounded(state)
        with self.db:
            self.db.execute('INSERT INTO state VALUES(1,?)', (encoded(state).decode(),))
            if audit:
                self.db.execute('INSERT INTO history VALUES(?,?,?)', (1, audit['fingerprint'], encoded(audit).decode()))
        return self.recover()

    def migrate_working_draft(self, input_path, *, actor, reason):
        from .attention_draft import prepare
        path = checked_local(input_path)
        raw = read_input(path, 10_000_000, 'E_ATTENTION_LIMIT')
        draft = load_json(raw)
        payload, themes, aliases, lookup = prepare(draft)
        _text(actor); _text(reason)
        binding = {'kind': 'file', 'path': str(path), 'fingerprint': digest(raw)}
        return self.build(payload, _working=(draft, themes, aliases, lookup, binding, actor, reason))

    def apply(self, patch=None, *, input_path=None):
        if input_path:
            patch = read_json(input_path)
        fingerprint = digest(encoded(patch))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute('SELECT 1 FROM history WHERE fingerprint=?', (fingerprint,)).fetchone()
            if not existing:
                state = self.state()
                changing_a = patch.get('schema') == 'attention-a-patch/1'
                require(state['b_material_status' if changing_a else 'material_status'] == 'current', 'E_ATTENTION_REVALIDATION')
                require(patch.get('schema') in {'attention-patch/1', 'attention-patch/2', 'attention-a-patch/1'} and patch.get('analysis_id') == state['analysis_id'], 'E_ATTENTION_PATCH')
                require(type(patch.get('base_revision')) is int and patch['base_revision'] == state['revision'], 'E_ATTENTION_CONFLICT')
                _text(patch.get('actor')); _text(patch.get('reason'))
                if changing_a:
                    from .attention_a import apply_reference
                    apply_reference(state, patch)
                elif patch['schema'] == 'attention-patch/2':
                    from .attention_model import apply_objects
                    apply_objects(state, patch)
                else:
                    self._apply_legacy(state, patch)
                bounded(state)
                state['revision'] += 1
                audit = {'revision': state['revision'], 'actor': patch['actor'], 'reason': patch['reason'], 'at': now(), 'fingerprint': fingerprint, 'patch': patch}
                self.db.execute('INSERT INTO history VALUES(?,?,?)', (state['revision'], fingerprint, encoded(audit).decode()))
                for key in ('history','material_status','b_material_status','a_material_status'): state.pop(key, None)
                self.db.execute('UPDATE state SET payload=? WHERE id=1', (encoded(state).decode(),))
        return self.recover()

    def import_a(self, input_path, *, actor, reason):
        from .attention_a import prepare_import
        return self.apply(prepare_import(input_path, self.state(), actor, reason))

    def _apply_legacy(self, state, patch):
        from .attention_model import apply_objects, normalize_facet
        require(isinstance(patch.get('edits'), list) and patch['edits'], 'E_ATTENTION_PATCH')
        edits = []
        for edit in patch['edits']:
            require(isinstance(edit, dict) and set(edit) == {'opinion_id', 'facet_id', 'record_id', 'evidence', 'interpretation', 'status'}, 'E_ATTENTION_PATCH')
            previous = next((o for o in state['opinions'] if o['opinion_id'] == edit['opinion_id']), None)
            if previous:
                require(previous['record_id'] == edit['record_id'] and previous['status'] != 'superseded', 'E_ATTENTION_IDENTITY')
                facets = copy.deepcopy(previous['facets'])
                matches = [f for f in facets if f['facet_id'] == edit['facet_id']]
                require(len(matches) == 1, 'E_ATTENTION_IDENTITY')
                matches[0].update({k: copy.deepcopy(edit[k]) for k in ('evidence', 'interpretation', 'status')})
            else:
                facets = [normalize_facet({k: copy.deepcopy(v) for k, v in edit.items() if k not in {'opinion_id', 'record_id'}})]
            result = {'opinion_id': edit['opinion_id'], 'record_id': edit['record_id'], 'facets': facets,
                      'interpretation': previous['interpretation'] if previous and len(facets) > 1 else edit['interpretation'],
                      'status': previous['status'] if previous and len(facets) > 1 else edit['status'],
                      'replaces': previous['replaces'] if previous else []}
            if previous and 'legacy_aliases' in previous:
                result['legacy_aliases'] = copy.deepcopy(previous['legacy_aliases'])
            edits.append(result)
        apply_objects(state, dict(patch, schema='attention-patch/2', edits=edits))

    def recover(self):
        from .attention_render import render
        state = self.state()
        try:
            atomic(checked_local(self.path / 'attention-state.json'), encoded(state))
            atomic(checked_local(self.path / 'attention.html'), render(state).encode('utf-8'))
        except Exception:
            raise ReviewError('E_ATTENTION_OUTPUT_RECOVER') from None
        return state
