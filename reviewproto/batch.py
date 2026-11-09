"""Thin local aggregate: read-only sources, frozen evidence, append-only decisions.

Source workspaces remain authoritative for opinions. This module never opens them
through Workspace.__init__ (which performs DDL), nor copies their private sections.
"""
from __future__ import annotations

import copy
from contextlib import closing
from pathlib import Path
import sqlite3

from .core import ReviewError, digest, require, validate_candidate
from .framework import MUTABLE_RULE, framework_digest, identifier, load_json, text, texts
from .store import Workspace, PRIVATE_IGNORE, atomic, encoded, linklike, now, read_input
from .understanding import current_views

LIMIT = 10_000_000


def checked_local(path):
    path = Path(path).absolute()
    require(all(not linklike(p) for p in [path, *path.parents]), 'E_BATCH_LINK')
    return path.resolve()


def bounded(value):
    require(len(encoded(value)) <= LIMIT, 'E_BATCH_LIMIT')
    return value


def read_json(path):
    return bounded(load_json(read_input(checked_local(path), LIMIT, 'E_BATCH_LIMIT')))


def source_state(path):
    """Reuse public frozen-source validation on a strictly read-only connection."""
    path = checked_local(path)
    dbpath = checked_local(path / 'review.sqlite3')
    # Workspace.__init__ normally guards these; the read-only adapter must
    # preserve that boundary without invoking its write-side initialization.
    for name in ('source.docx', 'source.json', 'source.csv', 'frameworks'):
        checked_local(path / name)
    require(dbpath.is_file(), 'E_BATCH_SOURCE')
    db = None
    try:
        db = sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)
        require(db.execute('PRAGMA application_id').fetchone()[0] == Workspace.APPLICATION_ID, 'E_BATCH_SOURCE')
        db.execute('PRAGMA query_only=ON')
        proxy = object.__new__(Workspace)
        proxy.path, proxy.db = path, db
        return proxy.state()
    except ReviewError:
        raise
    except Exception:
        raise ReviewError('E_BATCH_SOURCE') from None
    finally:
        if db is not None:
            db.close()


def selected_run_summary(state, candidates):
    run_ids = {c['value'].get('run_id') for c in candidates}
    return [dict(run_id=r['run_id'], status=r.get('status', 'unknown'),
        errors_count=len(r.get('errors', [])) + len(r.get('rejected', [])))
        for r in state.get('extraction_runs', []) if r['run_id'] in run_ids]


def select_source(selection, root):
    require(isinstance(selection, dict) and set(selection) == {'workspace', 'source_id', 'revision', 'section_ids', 'candidate_ids', 'view'}, 'E_BATCH_MANIFEST')
    require(isinstance(selection['workspace'], str) and selection['workspace'].strip(), 'E_BATCH_PATH')
    path = checked_local(root / selection['workspace'])
    state = source_state(path)
    require(selection['source_id'] == state['source']['source_id'], 'E_BATCH_SOURCE_ID')
    require(type(selection['revision']) is int and selection['revision'] == state['revision'], 'E_BATCH_SOURCE_REVISION')
    sections = selection['section_ids']
    ids = selection['candidate_ids']
    require(isinstance(sections, list) and sections and all(isinstance(s, str) for s in sections) and len(set(sections)) == len(sections), 'E_BATCH_SELECTION')
    require(isinstance(ids, list) and ids and all(isinstance(i, str) for i in ids) and len(set(ids)) == len(ids), 'E_BATCH_SELECTION')
    bysection = {s['section_id']: s for s in state['sections']}
    require(set(sections) <= set(bysection), 'E_BATCH_SELECTION')
    require(all(bysection[s]['visibility'] in {'author_visible', 'visibility_unknown'} for s in sections), 'E_BATCH_PRIVATE')
    view = selection['view']
    require(isinstance(view, dict) and set(view) == {'kind', 'run_id'}, 'E_BATCH_VIEW')
    require((view['kind'] in {'selected', 'effective'} and view['run_id'] is None) or
            (view['kind'] == 'run' and isinstance(view['run_id'], str) and any(r['run_id'] == view['run_id'] for r in state.get('extraction_runs', []))), 'E_BATCH_VIEW')
    candidates = {c['candidate_id']: c for c in current_views(state)}
    originals = {c['candidate_id']: c for c in state['candidates']}
    require(set(ids) <= set(candidates), 'E_BATCH_CANDIDATE')
    selected = []
    for cid in ids:
        candidate = candidates[cid]
        require(candidate['status'] not in {'rejected', 'withdrawn', 'superseded'}, 'E_BATCH_RESELECT_REQUIRED')
        require(candidate['section_id'] in sections, 'E_BATCH_SELECTION')
        if view['kind'] == 'effective':
            require(candidate['status'] == 'confirmed', 'E_BATCH_VIEW_CONFIRMED_REQUIRED')
        if view['kind'] == 'run':
            require(originals[cid].get('run_id') == view['run_id'], 'E_BATCH_VIEW')
        validate_candidate(candidate, state, allow_pending=candidate['status'] == 'pending_review')
        require(candidate['visibility'] == bysection[candidate['section_id']]['visibility'], 'E_BATCH_PRIVATE')
        selected.append(dict(value=copy.deepcopy(candidate), candidate_sha256=framework_digest(candidate)))
    latest = {d['candidate_id']: d['decision_id'] for d in state['decisions'] if d['candidate_id'] in ids}
    frozen = dict(workspace=str(path), source=copy.deepcopy(state['source']), revision=state['revision'],
                  view=copy.deepcopy(view), sections=[copy.deepcopy(bysection[s]) for s in sections],
                  scores=copy.deepcopy(state['scores']), candidates=selected, latest_decision_ids=latest)
    # Only status summaries of the selected extraction runs, never their raw
    # payloads (which can include unselected/private sections).
    frozen['extraction_status'] = selected_run_summary(state, selected)
    frozen['binding_sha256'] = framework_digest({k: v for k, v in frozen.items() if k != 'workspace'})
    return frozen


def manual_issues(entries, sources, framework):
    require(isinstance(entries, list) and len(entries) <= 1000, 'E_BATCH_ISSUES')
    rules = {r['rule_id']: r for r in framework['book']['rules']}
    refs = {(s['source']['source_id'], c['value']['candidate_id']) for s in sources for c in s['candidates']}
    result, seen = [], set()
    for entry in entries:
        basic = {'issue_id', 'title', 'rule_id', 'support', 'counter', 'rationale', 'after', 'unknowns'}
        extended = {'concept', 'alternatives', 'ranking', 'comparison', 'score_links'}
        require(isinstance(entry, dict) and (set(entry) == basic or set(entry) == basic | extended), 'E_BATCH_ISSUE')
        identifier(entry['issue_id'])
        require(entry['issue_id'] not in seen and entry['rule_id'] in rules, 'E_BATCH_ISSUE')
        seen.add(entry['issue_id'])
        text(entry['title']); text(entry['rationale']); texts(entry['unknowns'])
        used = set()
        for kind in ('support', 'counter'):
            require(isinstance(entry[kind], list), 'E_BATCH_EVIDENCE')
            for ref in entry[kind]:
                require(isinstance(ref, dict) and set(ref) == {'source_id', 'candidate_id'}, 'E_BATCH_EVIDENCE')
                key = (ref['source_id'], ref['candidate_id'])
                require(key in refs and key not in used, 'E_BATCH_EVIDENCE')
                used.add(key)
        require(used, 'E_BATCH_EVIDENCE')
        after = entry['after']
        require(isinstance(after, dict) and set(after) <= MUTABLE_RULE, 'E_BATCH_AFTER')
        for key, value in after.items():
            texts(value) if key in {'applicable_when', 'exceptions', 'checks'} else text(value)
        require('strength' not in after or after['strength'] in {'unknown', 'recommended', 'mandatory', 'optional'}, 'E_BATCH_AFTER')
        require('strength_provenance' not in after or after['strength_provenance'] in {'explicit', 'inferred', 'unknown'}, 'E_BATCH_AFTER')
        if set(entry) == basic | extended:
            from .batch_discovery import validate_issue
            validate_issue(entry, sources, rules[entry['rule_id']])
        item = copy.deepcopy(entry)
        item.update(origin='manual', before=copy.deepcopy(rules[entry['rule_id']]),
                    evidence_scope='baseline_only', after_provenance='editorial_proposal', authority='unconfirmed')
        item['issue_sha256'] = framework_digest(item)
        result.append(item)
    return result


class BatchWorkspace:
    APPLICATION_ID = 0x52564231

    def __init__(self, path):
        self.path = checked_local(path)
        require(self.path.parent != self.path and not (self.path / '.git').exists(), 'E_BATCH_DEDICATED')
        self.path.mkdir(parents=True, exist_ok=True)
        target = self.path / 'batch.sqlite3'
        for item in self.path.iterdir():
            require(not linklike(item), 'E_BATCH_LINK')
        if not target.exists():
            require(not any(self.path.iterdir()), 'E_BATCH_DEDICATED')
        else:
            with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as check:
                require(check.execute('PRAGMA application_id').fetchone()[0] == self.APPLICATION_ID, 'E_BATCH_DEDICATED')
        ignore = self.path / '.gitignore'
        if ignore.exists():
            require(read_input(ignore, 4096) == PRIVATE_IGNORE, 'E_BATCH_DEDICATED')
        else:
            with ignore.open('xb') as stream:
                stream.write(PRIVATE_IGNORE)
        self.db = sqlite3.connect(target, timeout=10, isolation_level=None)
        self.db.execute(f'PRAGMA application_id={self.APPLICATION_ID}')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')

    def close(self):
        self.db.close()

    def state(self):
        row = self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        require(row is not None, 'E_BATCH_EMPTY')
        state = load_json(row[0])
        stale = False
        source_runs = []
        for source in state['sources']:
            summary = source.get('extraction_status', [])
            try:
                actual = source_state(source['workspace'])
                summary = selected_run_summary(actual, source['candidates'])
                selection = dict(workspace=source['workspace'], source_id=source['source']['source_id'], revision=source['revision'],
                                 section_ids=[s['section_id'] for s in source['sections']], candidate_ids=[c['value']['candidate_id'] for c in source['candidates']], view=source['view'])
                current = select_source(selection, Path.cwd())
                if 'extraction_status' not in source:
                    current.pop('extraction_status', None)
                    current['binding_sha256'] = framework_digest({k: v for k, v in current.items() if k not in {'workspace', 'binding_sha256'}})
                require(actual['revision'] == source['revision'] and current['binding_sha256'] == source['binding_sha256'], 'E_BATCH_SOURCE_CHANGED')
            except ReviewError:
                stale = True
            source_runs.append(dict(source_id=source['source']['source_id'], runs=summary))
        # Derived status summaries also cover pre-T2 frozen packages; do not
        # mutate their frozen source bindings or historical package digests.
        state['source_run_status'] = source_runs
        try:
            frame = state['framework']
            frames = source_state(frame['workspace']).get('frameworks', [])
            require(any(f['sha256'] == frame['sha256'] and f['book'] == frame['book'] for f in frames), 'E_BATCH_FRAMEWORK')
        except ReviewError:
            stale = True
        state['material_status'] = 'needs_refresh' if stale else 'current'
        for decision in state['decisions']:
            decision['validity'] = 'current' if not stale and decision['package_sha256'] == state['package_sha256'] else 'needs_revalidation'
        for issue in state['issues']:
            issue['validity'] = 'needs_revalidation' if stale else 'current'
        for run in state.get('analysis_runs', []):
            from .batch_discovery import input_binding
            run['validity'] = 'current' if not stale and run.get('input_sha256') == input_binding(state) else 'needs_revalidation'
        return state

    def review_template(self):
        state = self.state()
        return dict(schema_version=1, batch_id=state['batch_id'], base_revision=state['revision'], actor='', reason='',
                    package_sha256=state['package_sha256'], decisions=[])

    def recover(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state = self.state()
            self._publish(state)
            self.db.execute('COMMIT')
            return state
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def apply(self, payload=None, *, input_path=None):
        if input_path is not None:
            payload = read_json(input_path)
        bounded(payload)
        require(isinstance(payload, dict) and set(payload) == {'schema_version', 'batch_id', 'base_revision', 'actor', 'reason', 'package_sha256', 'decisions'} and
                type(payload['schema_version']) is int and payload['schema_version'] == 1, 'E_BATCH_PATCH')
        text(payload['actor']); text(payload['reason'])
        require(isinstance(payload['decisions'], list) and 0 < len(payload['decisions']) <= 1000, 'E_BATCH_PATCH')
        fingerprint = framework_digest(payload)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state = self.state()
            require(payload['batch_id'] == state['batch_id'], 'E_BATCH_ID')
            if any(d['patch_sha256'] == fingerprint for d in state['decisions']):
                self._publish(state)
                self.db.execute('COMMIT')
                return state
            require(type(payload['base_revision']) is int and payload['base_revision'] == state['revision'], 'E_BATCH_REVISION')
            require(payload['package_sha256'] == state['package_sha256'], 'E_BATCH_PACKAGE')
            require(state['material_status'] == 'current', 'E_BATCH_STALE')
            issues = {i['issue_id']: i for i in state['issues']}
            additions, seen = [], set()
            for row in payload['decisions']:
                fields = {'issue_id', 'decision_type', 'case_source_id', 'action', 'reason'}
                require(isinstance(row, dict) and set(row) in (fields, fields | {'alternative_id'}), 'E_BATCH_DECISION')
                require(row['issue_id'] in issues and row['decision_type'] in {'case_decision', 'framework_proposal_review'} and
                        row['action'] in {'keep', 'change', 'need_material', 'defer'}, 'E_BATCH_DECISION')
                case_ids = {r['source_id'] for kind in ('support', 'counter') for r in issues[row['issue_id']][kind]}
                require((row['decision_type'] == 'case_decision' and isinstance(row['case_source_id'], str) and row['case_source_id'] in case_ids) or
                        (row['decision_type'] == 'framework_proposal_review' and row['case_source_id'] is None), 'E_BATCH_CASE_SCOPE')
                key = (row['issue_id'], row['decision_type'], row['case_source_id'])
                require(key not in seen, 'E_BATCH_DECISION_DUPLICATE')
                seen.add(key)
                text(row['reason'])
                issue = issues[row['issue_id']]
                variants = {a['alternative_id']: a for a in issue.get('alternatives', [])}
                selected_id = row.get('alternative_id')
                if variants and row['action'] == 'change':
                    require(isinstance(selected_id, str) and selected_id in variants and selected_id != 'retain', 'E_BATCH_ALTERNATIVE_REQUIRED')
                else:
                    require(selected_id is None or isinstance(selected_id, str) and selected_id in variants, 'E_BATCH_ALTERNATIVE')
                if variants and row['action'] == 'keep':
                    require(selected_id in (None, 'retain'), 'E_BATCH_ALTERNATIVE')
                    selected_id = 'retain'
                item = copy.deepcopy(row)
                if variants:
                    selected = variants.get(selected_id)
                    item.update(alternative_id=selected_id, selected_after=copy.deepcopy(selected['after']) if selected else None,
                                alternative_sha256=framework_digest(selected) if selected else None)
                item.update(actor=payload['actor'], patch_reason=payload['reason'], at=now(), revision=state['revision'] + 1,
                            package_sha256=state['package_sha256'], issue_sha256=issues[row['issue_id']]['issue_sha256'],
                            patch_sha256=fingerprint, authority='unconfirmed', validity='current')
                item['decision_id'] = framework_digest(item)
                additions.append(item)
            state['decisions'].extend(additions)
            state['revision'] += 1
            bounded(state)
            self.db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (encoded(state).decode('utf-8'),))
            self._publish(state)
            self.db.execute('COMMIT')
            return state
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def _publish(self, state):
        from .batch_render import render
        for name, data in [('state.json', encoded(state)), ('report.html', render(state).encode('utf-8'))]:
            checked_local(self.path / name)
            atomic(self.path / name, data)

    def append_analysis(self, payload=None, *, input_path=None):
        """Append grounded candidate issues without replacing manual work.

        Producer owns discovery, not authority. The caller must bind the exact
        package/revision it analysed. Same run+payload retries are idempotent.
        T2 may extend the issue schema for alternatives at this public seam.
        """
        if input_path is not None:
            payload = read_json(input_path)
        bounded(payload)
        fields = {'schema_version', 'batch_id', 'base_revision', 'package_sha256', 'run_id', 'provenance', 'issues'}
        require(isinstance(payload, dict) and set(payload) in (fields, fields | {'analysis'}) and
                type(payload['schema_version']) is int and payload['schema_version'] == 1, 'E_BATCH_ANALYSIS')
        identifier(payload['run_id']); text(payload['provenance'])
        fingerprint = framework_digest(payload)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state = self.state()
            require(payload['batch_id'] == state['batch_id'], 'E_BATCH_ID')
            previous = next((r for r in state.get('analysis_runs', []) if r['run_id'] == payload['run_id']), None)
            if previous:
                require(previous['payload_sha256'] == fingerprint, 'E_BATCH_RUN_CONFLICT')
                self._publish(state)
                self.db.execute('COMMIT')
                return state
            require(type(payload['base_revision']) is int and payload['base_revision'] == state['revision'], 'E_BATCH_REVISION')
            require(payload['package_sha256'] == state['package_sha256'], 'E_BATCH_PACKAGE')
            require(state['material_status'] == 'current', 'E_BATCH_STALE')
            additions = manual_issues(payload['issues'], state['sources'], state['framework'])
            require(additions or 'analysis' in payload, 'E_BATCH_ISSUES')
            if 'analysis' in payload:
                from .batch_discovery import validate_analysis
                validate_analysis(payload['analysis'], additions, state)
            ids = {i['issue_id'] for i in state['issues']}
            require(not ids.intersection(i['issue_id'] for i in additions), 'E_BATCH_ISSUE_CONFLICT')
            for issue in additions:
                issue.pop('issue_sha256')
                issue.update(origin='analysis_candidate', analysis_run_id=payload['run_id'], provenance=payload['provenance'])
                issue['issue_sha256'] = framework_digest(issue)
            state['issues'].extend(additions)
            state.setdefault('analysis_runs', []).append(dict(run_id=payload['run_id'], provenance=payload['provenance'], payload_sha256=fingerprint,
                input_package_sha256=payload['package_sha256'], at=now(), issue_ids=[i['issue_id'] for i in additions], **copy.deepcopy(payload.get('analysis', {}))))
            package = {k: state[k] for k in ('sources', 'framework', 'issues')}
            state['package_sha256'] = framework_digest(package)
            state['revision'] += 1
            state['package_history'].append(dict(package_sha256=state['package_sha256'], at=now(), **copy.deepcopy(package)))
            bounded(state)
            self.db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (encoded(state).decode('utf-8'),))
            state = self.state()
            self.db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (encoded(state).decode('utf-8'),))
            self._publish(state)
            self.db.execute('COMMIT')
            return state
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def build(self, manifest, manifest_root=None):
        bounded(manifest)
        require(isinstance(manifest, dict) and set(manifest) == {'schema_version', 'batch_id', 'sources', 'framework', 'issues'} and type(manifest['schema_version']) is int and manifest['schema_version'] == 1, 'E_BATCH_MANIFEST')
        identifier(manifest['batch_id'])
        require(isinstance(manifest['sources'], list) and 0 < len(manifest['sources']) <= 100, 'E_BATCH_MANIFEST')
        root = checked_local(manifest_root or Path.cwd())
        sources, seen = [], {}
        for selection in manifest['sources']:
            frozen = select_source(selection, root)
            require(not self.path.is_relative_to(Path(frozen['workspace'])) and not Path(frozen['workspace']).is_relative_to(self.path), 'E_BATCH_PATH')
            sid = frozen['source']['source_id']
            if sid in seen:
                require(seen[sid] == frozen['binding_sha256'], 'E_BATCH_SOURCE_DUPLICATE')
                continue
            seen[sid] = frozen['binding_sha256']
            sources.append(frozen)
        choice = manifest['framework']
        require(isinstance(choice, dict) and set(choice) == {'workspace', 'sha256'} and isinstance(choice['workspace'], str), 'E_BATCH_FRAMEWORK')
        framework_path = checked_local(root / choice['workspace'])
        frames = source_state(framework_path).get('frameworks', [])
        framework = next((f for f in frames if f['sha256'] == choice['sha256']), None)
        require(framework is not None, 'E_BATCH_FRAMEWORK')
        framework = copy.deepcopy(framework)
        framework['workspace'] = str(framework_path)
        issues = manual_issues(manifest['issues'], sources, framework)
        package = bounded(dict(sources=sources, framework=framework, issues=issues))
        fingerprint = framework_digest(package)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            if old:
                state = load_json(old[0])
                require(state['batch_id'] == manifest['batch_id'], 'E_BATCH_ID')
                if state['package_sha256'] == fingerprint:
                    self._publish(state)
                    self.db.execute('COMMIT')
                    return state
            else:
                state = dict(schema_version=1, batch_id=manifest['batch_id'], revision=0, decisions=[], package_history=[])
            state.update(package)
            state['revision'] += 1
            state['package_sha256'] = fingerprint
            state['package_history'].append(dict(package_sha256=fingerprint, at=now(), sources=copy.deepcopy(sources), framework=copy.deepcopy(framework), issues=copy.deepcopy(issues)))
            bounded(state)
            self.db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (encoded(state).decode('utf-8'),))
            state = self.state()
            self.db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (encoded(state).decode('utf-8'),))
            self._publish(state)
            self.db.execute('COMMIT')
            return state
        except Exception:
            self.db.execute('ROLLBACK')
            raise
