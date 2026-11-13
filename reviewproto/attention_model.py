"""Attention editing rules shared by the public Workspace and draft Adapter."""
import copy

from .core import require

STATUSES = {'working', 'needs_review', 'confirmed', 'withdrawn'}
FACET_FIELDS = {'facet_id', 'kind', 'interpretation', 'evidence', 'status', 'themes', 'a_links', 'outside', 'expression', 'qualifiers', 'legacy_aliases'}
QUALIFIERS = {'object', 'direction', 'degree', 'negation', 'reasons', 'conditions', 'actions', 'examples', 'alternatives'}


def text(value):
    require(isinstance(value, str) and bool(value.strip()), 'E_ATTENTION_TEXT')
    return value


def evidence(record, items):
    require(isinstance(items, list) and items, 'E_ATTENTION_EVIDENCE')
    for ev in items:
        require(isinstance(ev, dict) and set(ev) == {'source_id', 'section_id', 'start', 'end', 'quote'}, 'E_ATTENTION_EVIDENCE')
        sections = [s for s in record['sections'] if s['section_id'] == ev['section_id']]
        require(len(sections) == 1, 'E_ATTENTION_SECTION')
        raw = sections[0]['text']
        require(type(ev['start']) is int and type(ev['end']) is int and 0 <= ev['start'] < ev['end'] <= len(raw), 'E_ATTENTION_RANGE')
        require(ev['source_id'] == record['source_id'] and raw[ev['start']:ev['end']] == ev['quote'], 'E_ATTENTION_QUOTE')


def normalize_facet(facet):
    result = copy.deepcopy(facet)
    result.setdefault('kind', 'content')
    for key in ('themes', 'a_links', 'outside', 'legacy_aliases'):
        result.setdefault(key, [])
    result.setdefault('expression', {'function': '', 'boilerplate_candidate': None})
    result.setdefault('qualifiers', {})
    require(isinstance(result['qualifiers'], dict), 'E_ATTENTION_QUALIFIERS')
    for key in QUALIFIERS:
        result['qualifiers'].setdefault(key, '')
    return result


def upgrade(state):
    """T1 packages get an explicit single-facet representation without new identity."""
    state.setdefault('model_version', 'attention-objects/2')
    state.setdefault('legacy_aliases', [])
    for op in state['opinions']:
        if 'facets' not in op:
            op['facets'] = [normalize_facet({k: copy.deepcopy(op[k]) for k in FACET_FIELDS if k in op})]
        op.setdefault('replaces', [])
        op.setdefault('superseded_by', [])
    return state


def project(op):
    # A compatibility projection is provided only where there is one exact facet.
    if len(op['facets']) == 1:
        facet = op['facets'][0]
        for key in ('facet_id', 'evidence', 'themes', 'a_links', 'outside', 'expression', 'qualifiers'):
            op[key] = copy.deepcopy(facet[key])
    else:
        for key in ('facet_id', 'themes', 'a_links', 'outside', 'expression', 'qualifiers'):
            op.pop(key, None)
        op['evidence'] = [copy.deepcopy(e) for f in op['facets'] for e in f['evidence']]


def apply_objects(state, patch):
    upgrade(state)
    require(set(patch) <= {'schema', 'analysis_id', 'base_revision', 'actor', 'reason', 'edits', 'themes', 'relations'}, 'E_ATTENTION_PATCH')
    edits = patch.get('edits', [])
    themes = patch.get('themes', [])
    relations = patch.get('relations', [])
    require(all(isinstance(x, list) for x in (edits, themes, relations)) and bool(edits or themes or relations), 'E_ATTENTION_PATCH')
    records = {r['record_id']: r for r in state['records']}
    opinions = {o['opinion_id']: o for o in state['opinions']}
    old_facets = {f['facet_id']: (o, f) for o in state['opinions'] for f in o['facets']}
    seen, seen_facets, replaced, affected = set(), set(), set(), set()
    for edit in edits:
        require(isinstance(edit, dict) and set(edit) <= {'opinion_id', 'record_id', 'interpretation', 'status', 'facets', 'replaces', 'legacy_aliases'}, 'E_ATTENTION_PATCH')
        oid = text(edit.get('opinion_id'))
        require(oid not in seen, 'E_ATTENTION_DUPLICATE'); seen.add(oid)
        record = records.get(edit.get('record_id'))
        require(record is not None, 'E_ATTENTION_RECORD')
        previous = opinions.get(oid)
        require(previous is None or previous['record_id'] == record['record_id'] and previous['status'] != 'superseded', 'E_ATTENTION_IDENTITY')
        text(edit.get('interpretation'))
        require(edit.get('status') in STATUSES, 'E_ATTENTION_STATUS')
        facets = edit.get('facets')
        require(isinstance(facets, list) and facets, 'E_ATTENTION_FACETS')
        new_facets = []
        for raw in facets:
            require(isinstance(raw, dict) and set(raw) <= FACET_FIELDS, 'E_ATTENTION_PATCH')
            fid = text(raw.get('facet_id'))
            require(fid not in seen_facets, 'E_ATTENTION_DUPLICATE'); seen_facets.add(fid)
            old = old_facets.get(fid)
            require(old is None or old[0]['opinion_id'] == oid, 'E_ATTENTION_IDENTITY')
            facet = normalize_facet(raw)
            text(facet.get('interpretation')); evidence(record, facet.get('evidence'))
            require(facet.get('status') in STATUSES, 'E_ATTENTION_STATUS')
            require(facet['kind'] in {'content', 'disposition'}, 'E_ATTENTION_KIND')
            expr = facet['expression']
            require(isinstance(expr, dict) and set(expr) == {'function', 'boilerplate_candidate'} and isinstance(expr['function'], str) and (expr['boilerplate_candidate'] is None or type(expr['boilerplate_candidate']) is bool), 'E_ATTENTION_EXPRESSION')
            require(isinstance(facet['qualifiers'], dict) and set(facet['qualifiers']) <= QUALIFIERS and all(isinstance(v, str) or isinstance(v, list) and all(isinstance(item, str) for item in v) for v in facet['qualifiers'].values()), 'E_ATTENTION_QUALIFIERS')
            # T3 owns A edits; T2 cannot silently invent or transfer an A association.
            for field in ('a_links', 'outside'):
                require(facet[field] == (old[1][field] if old else []), 'E_ATTENTION_A_EDIT')
            if old and any(facet.get(k) != old[1].get(k) for k in ('interpretation', 'evidence', 'qualifiers', 'kind')):
                affected.add(fid)
                for field in ('a_links', 'outside'):
                    for link in facet[field]:
                        if link.get('status') != 'withdrawn':
                            link['status'] = 'needs_review'
            require(isinstance(facet['themes'], list), 'E_ATTENTION_THEME')
            for member in facet['themes']:
                require(isinstance(member, dict) and set(member) == {'theme_id', 'reason', 'evidence', 'status'}, 'E_ATTENTION_THEME')
                text(member['theme_id']); text(member['reason']); evidence(record, member['evidence'])
                require(member['status'] in STATUSES, 'E_ATTENTION_STATUS')
            new_facets.append(facet)
        if previous:
            require({f['facet_id'] for f in previous['facets']} <= {f['facet_id'] for f in new_facets}, 'E_ATTENTION_IDENTITY')
            require(edit.get('replaces', previous['replaces']) == previous['replaces'], 'E_ATTENTION_IDENTITY')
        replacements = edit.get('replaces', previous['replaces'] if previous else [])
        require(isinstance(replacements, list) and len(replacements) == len(set(replacements)), 'E_ATTENTION_IDENTITY')
        for parent in replacements if not previous else []:
            require(parent in opinions and parent != oid and opinions[parent]['record_id'] == record['record_id'] and opinions[parent]['status'] != 'superseded', 'E_ATTENTION_IDENTITY')
            replaced.add(parent)
        result = dict(copy.deepcopy(edit), facets=new_facets, replaces=replacements, superseded_by=[])
        if previous:
            result['superseded_by'] = previous['superseded_by']
            state['opinions'][state['opinions'].index(previous)] = result
        else:
            state['opinions'].append(result)
        project(result)
        opinions[oid] = result
    # Replacement parents remain in place; every old association keeps its old endpoint.
    for op in state['opinions']:
        if op['opinion_id'] in replaced:
            op['status'] = 'superseded'
            op['superseded_by'] = [o['opinion_id'] for o in state['opinions'] if op['opinion_id'] in o['replaces']]
            for facet in op['facets']:
                affected.add(facet['facet_id'])
                facet['status'] = 'superseded'
                for field in ('themes', 'a_links', 'outside'):
                    for link in facet[field]:
                        if link.get('status') != 'withdrawn':
                            link['status'] = 'needs_review'
            project(op)
    changed_themes = set()
    for key, incoming, identity, allowed in (
        ('themes', themes, 'theme_id', {'theme_id', 'label', 'definition', 'parent_ids', 'status', 'legacy_aliases'}),
        ('relations', relations, 'relation_id', {'relation_id', 'type', 'endpoints', 'direction', 'scope', 'evidence', 'reading', 'ambiguity', 'status', 'legacy_aliases'})):
        changed = set()
        for raw in incoming:
            require(isinstance(raw, dict) and set(raw) <= allowed, 'E_ATTENTION_PATCH')
            ident = text(raw.get(identity))
            require(ident not in changed, 'E_ATTENTION_DUPLICATE'); changed.add(ident)
            require(raw.get('status') in STATUSES, 'E_ATTENTION_STATUS')
            old = next((x for x in state[key] if x[identity] == ident), None)
            if old:
                if key == 'themes':
                    raw = copy.deepcopy(raw)
                    changed_definition = raw.get('definition') != old.get('definition') or raw.get('parent_ids') != old.get('parent_ids')
                    raw['version'] = old.get('version', 1) + int(changed_definition)
                    if changed_definition:
                        raw['status'] = 'needs_review'
                        changed_themes.add(ident)
                state[key][state[key].index(old)] = copy.deepcopy(raw)
            else:
                state[key].append(copy.deepcopy(raw))
    facets = {f['facet_id']: (o, f) for o in state['opinions'] for f in o['facets']}
    tids = {t['theme_id'] for t in state['themes']}
    for theme in state['themes']:
        text(theme.get('label')); text(theme.get('definition'))
        require(isinstance(theme.get('parent_ids'), list) and set(theme['parent_ids']) <= tids and theme['theme_id'] not in theme['parent_ids'], 'E_ATTENTION_THEME')
    def visit(tid, path):
        require(tid not in path, 'E_ATTENTION_THEME_CYCLE')
        for parent in next(t for t in state['themes'] if t['theme_id'] == tid)['parent_ids']:
            visit(parent, path | {tid})
    for tid in tids:
        visit(tid, set())
    for _, facet in facets.values():
        for link in facet['themes']:
            require(link['theme_id'] in tids, 'E_ATTENTION_THEME')
            if facet['facet_id'] in affected or link['theme_id'] in changed_themes:
                if link['status'] != 'withdrawn':
                    link['status'] = 'needs_review'
                next(t for t in state['themes'] if t['theme_id'] == link['theme_id'])['status'] = 'needs_review'
    for rel in state['relations']:
        for field in ('type', 'direction', 'scope', 'reading'):
            text(rel.get(field))
        require(isinstance(rel.get('ambiguity'), str), 'E_ATTENTION_RELATION')
        require(isinstance(rel.get('endpoints'), list) and rel['endpoints'], 'E_ATTENTION_RELATION')
        endpoint_records = set()
        for endpoint in rel['endpoints']:
            require(isinstance(endpoint, dict) and set(endpoint) == {'facet_id', 'role'} and endpoint['facet_id'] in facets, 'E_ATTENTION_RELATION')
            text(endpoint['role']); endpoint_records.add(facets[endpoint['facet_id']][0]['record_id'])
        require(isinstance(rel.get('evidence'), list) and rel['evidence'], 'E_ATTENTION_EVIDENCE')
        for ev in rel['evidence']:
            matches = [r for rid, r in records.items() if rid in endpoint_records and r['source_id'] == ev.get('source_id') and any(s['section_id'] == ev.get('section_id') for s in r['sections'])]
            require(len(matches) == 1, 'E_ATTENTION_RECORD'); evidence(matches[0], [ev])
        if rel['status'] != 'withdrawn' and affected & {e['facet_id'] for e in rel['endpoints']}:
            rel['status'] = 'needs_review'
    for op in state['opinions']:
        project(op)
    return state
