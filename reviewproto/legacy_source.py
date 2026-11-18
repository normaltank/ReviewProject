"""Read verified original material from historical workspaces without old writers."""
from __future__ import annotations

import sqlite3

from .core import SCHEMA, ReviewError, digest, parse_docx, require
from .intake import parse_structured
from .local_io import checked_local, encoded, load_json, read_input

APPLICATION_ID = 0x52565031
SOURCE_FILES = {
    'native_docx': 'source.docx',
    'structured_json': 'source.json',
    'structured_csv': 'source.csv',
}


def section_identity(state, section):
    return {'source_id': state['source']['source_id'], 'revision': state['revision'],
            'section_id': section['section_id'], 'section_fingerprint': digest(encoded(section))}


def read_source_workspace(path):
    """Return only source identity, revision, raw scores and verified sections.

    Historical candidates, frameworks and their sidecars do not participate in
    original-material validation. The caller explicitly selects ordinary sections.
    No database migrations, projection repairs or framework refreshes take place.
    """
    path = checked_local(path)
    dbpath = checked_local(path / 'review.sqlite3')
    for name in (*SOURCE_FILES.values(), 'review.sqlite3-wal', 'review.sqlite3-shm', 'review.sqlite3-journal'):
        checked_local(path / name)
    require(dbpath.is_file(), 'E_BATCH_SOURCE')
    db = None
    try:
        db = sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)
        db.execute('PRAGMA query_only=ON')
        require(db.execute('PRAGMA application_id').fetchone()[0] == APPLICATION_ID, 'E_BATCH_SOURCE')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require({'state', 'runs', 'patches'} <= tables, 'E_BATCH_SOURCE')
        row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        require(row is not None, 'E_WORKSPACE_EMPTY')
        state = load_json(row[0])
        require(state.get('schema_version') == SCHEMA, 'E_SCHEMA_VERSION')
        source = state['source']
        kind = source['kind']
        require(kind in SOURCE_FILES, 'E_SOURCE_KIND')
        filename = SOURCE_FILES[kind]
        require(source.get('storage_file', filename) == filename, 'E_SOURCE_KIND')
        require(type(state['revision']) is int and state['revision'] >= 0, 'E_BATCH_SOURCE')
        data = read_input(path / filename, 40_000_000)
        fingerprint = digest(data)
        try:
            require(fingerprint == source['sha256'], 'E_SOURCE_CHANGED')
            verified = parse_docx(data) if kind == 'native_docx' else parse_structured(data, kind)
            require(verified['source']['source_id'] == source['source_id'] and
                    verified['scores'] == state['scores'] and verified['sections'] == state['sections'],
                    'E_REIMPORT_REQUIRED')
        except ReviewError as error:
            error.source_fingerprint = fingerprint
            raise
        return {key: state[key] for key in ('source', 'revision', 'scores', 'sections')}
    except ReviewError:
        raise
    except Exception:
        raise ReviewError('E_BATCH_SOURCE') from None
    finally:
        if db is not None:
            db.close()
