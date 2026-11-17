"""Synthetic historical source workspaces, independent of the retired writer."""
import json
import sqlite3
from pathlib import Path

from reviewproto.core import parse_docx
from reviewproto.intake import parse_structured


def create_legacy_workspace(path, payload=None, *, data=None, kind='structured_json', revision=0, state_updates=None):
    path = Path(path)
    path.mkdir(parents=True)
    if data is None:
        payload = payload if payload is not None else {
            'scores': [{'label': '原分', 'raw_value': ' 3.50 '}],
            'sections': [
                {'section_id': 'ordinary', 'label': '评审意见', 'text': '普通😀。若不能补证，可降低结论。'},
                {'section_id': 'private', 'label': '其他意见（作者不可见）', 'text': 'PRIVATE_NEVER_COPY'}]}
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    state = parse_docx(data) if kind == 'native_docx' else parse_structured(data, kind)
    state['source']['origin'] = 'synthetic'
    state['revision'] = revision
    if state_updates:
        state.update(state_updates)
    filename = {'native_docx': 'source.docx', 'structured_json': 'source.json', 'structured_csv': 'source.csv'}[kind]
    (path / filename).write_bytes(data)
    db = sqlite3.connect(path / 'review.sqlite3')
    try:
        db.execute('PRAGMA application_id=1381388337')
        db.execute('CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        db.execute('CREATE TABLE runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE patches(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('INSERT INTO state VALUES(1, ?)', (json.dumps(state, ensure_ascii=False),))
        db.commit()
    finally:
        db.close()
    return state
