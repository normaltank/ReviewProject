"""Pure saved-state record distribution. No workspace, IO, or inferred identity."""
from copy import deepcopy

_INACTIVE = {'withdrawn', 'superseded'}
_KINDS = ('explicit', 'partial', 'related', 'undetermined', 'needs_review')


def summarize(state, filters=None):
    """Return JSON-safe, reproducible sets; see docs/ATTENTION_SUMMARY.md."""
    filters = filters or {}
    supported = {'record_ids', 'paper_ids', 'directions', 'statuses', 'functions', 'boilerplate_candidate'}
    if set(filters) - supported:
        raise ValueError('Unknown summary filter')
    records = {r['record_id']: r for r in state.get('records', [])}
    universe = set(records)
    if 'record_ids' in filters:
        universe &= set(filters['record_ids'])
    if 'paper_ids' in filters:
        universe &= {rid for rid, r in records.items() if r.get('locator', {}).get('paper_id') in filters['paper_ids']}

    def matches(facet):
        expression = facet.get('expression') or {}
        values = {'directions': (facet.get('qualifiers') or {}).get('direction') or '未说明',
                  'statuses': facet.get('status', 'working'), 'functions': expression.get('function')}
        for key, value in values.items():
            candidates = value if isinstance(value, list) else [value]
            if key in filters and not any(v in filters[key] for v in candidates):
                return False
        return ('boilerplate_candidate' not in filters or
                expression.get('boilerplate_candidate') is filters['boilerplate_candidate'])

    def metric(ids):
        ids = sorted(set(ids) & universe)
        return dict(count=len(ids), denominator=len(universe), record_ids=ids,
                    ratio=len(ids) / len(universe) if universe else None)

    themes = {t['theme_id']: t for t in state.get('themes', [])}
    theme_sets = {t: set() for t in themes}
    reference = state.get('a_reference') or {}
    items = {a['id']: a for a in reference.get('items', [])}
    parts = {p['id']: p for p in reference.get('parts', [])}
    item_sets = {a: {k: set() for k in _KINDS} for a in items}
    part_sets = {p: {k: set() for k in _KINDS} for p in parts}
    unassigned = {k: set() for k in _KINDS}
    details = {rid: dict(record=deepcopy(records[rid]), facets=[]) for rid in sorted(universe)}
    groups = {k: dict(opinions=set(), facets=set(), records=set()) for k in ('content', 'disposition')}
    directions = {}; statuses = {}; outside = {}; selected_facets = {}
    seen = set(); contributions = []
    for opinion in state.get('opinions', []):
        rid = opinion['record_id']
        if rid not in universe or opinion.get('status') in _INACTIVE:
            continue
        for facet in opinion.get('facets', []):
            if facet.get('status') in _INACTIVE:
                continue
            if not matches(facet):
                continue
            identity = (opinion['opinion_id'], facet['facet_id'])
            if identity in seen:
                continue
            seen.add(identity)
            kind = facet.get('kind', 'content')
            if kind not in groups:
                continue
            group = groups[kind]
            group['opinions'].add(opinion['opinion_id']); group['facets'].add(facet['facet_id']); group['records'].add(rid)
            selected_facets[facet['facet_id']] = rid
            details[rid]['facets'].append(dict(opinion_id=opinion['opinion_id'],
                                              opinion_status=opinion.get('status', 'working'),
                                              opinion_interpretation=opinion.get('interpretation', ''), facet=deepcopy(facet)))
            direction = (facet.get('qualifiers') or {}).get('direction') or '未说明'
            direction_values = direction if isinstance(direction, list) else [direction]
            contribution = dict(record_id=rid, opinion_id=opinion['opinion_id'], facet_id=facet['facet_id'],
                                kind=kind, status=facet.get('status', 'working'), directions=deepcopy(direction_values),
                                expression=deepcopy(facet.get('expression') or {}), theme_ids=[],
                                a_items=[], a_parts=[], a_unassigned=[], outside=[])
            contributions.append(contribution)
            if kind != 'content':
                continue
            for direction_value in direction_values:
                directions.setdefault(direction_value, set()).add(rid)
            statuses.setdefault(facet.get('status', 'working'), set()).add(rid)
            for entry in facet.get('outside', []):
                status = entry.get('status', 'needs_review')
                if status not in _INACTIVE:
                    outside.setdefault(status, set()).add(rid)
                    contribution['outside'].append(status)
            for member in facet.get('themes', []):
                if member.get('status') in _INACTIVE:
                    continue
                pending = [member['theme_id']]; visited = set()
                while pending:
                    tid = pending.pop()
                    if tid in visited or tid not in themes or themes[tid].get('status') in _INACTIVE:
                        continue
                    visited.add(tid); theme_sets[tid].add(rid)
                    if tid not in contribution['theme_ids']:
                        contribution['theme_ids'].append(tid)
                    pending.extend(themes[tid].get('parent_ids', []))
            for link in facet.get('a_links', []):
                aid = link.get('a_item_id'); kind = link.get('kind')
                if link.get('status') in _INACTIVE:
                    continue
                if (aid not in items and not (aid is None and kind == 'undetermined') or
                        link.get('version') != reference.get('version') or
                        link.get('status') not in {'working', 'confirmed'} or
                        facet.get('status') == 'needs_review' or
                        state.get('a_material_status', state.get('material_status', 'current')) == 'needs_revalidation' or
                        state.get('b_material_status') == 'needs_revalidation' or
                        kind not in _KINDS):
                    kind = 'needs_review'
                if aid not in items:
                    unassigned[kind].add(rid)
                    contribution['a_unassigned'].append(kind)
                    continue
                item_sets[aid][kind].add(rid)
                contribution['a_items'].append(dict(id=aid, kind=kind))
                part = items[aid].get('part_id')
                if part in parts:
                    part_sets[part][kind].add(rid)
                    contribution['a_parts'].append(dict(id=part, kind=kind))
            contribution['theme_ids'].sort()
    relations = {}; relation_details = []
    for relation in state.get('relations', []):
        if relation.get('status') in _INACTIVE:
            continue
        relations.setdefault(relation['type'], set())
        endpoints = relation.get('endpoints', [])
        # A relation is visible only when all of its actual endpoints survive.
        if not endpoints or any(e['facet_id'] not in selected_facets for e in endpoints):
            continue
        relation_details.append(deepcopy(relation))
        relations.setdefault(relation['type'], set()).update(selected_facets[e['facet_id']] for e in endpoints)

    def auxiliary(group):
        result = {}
        for key in ('opinions', 'facets'):
            result[key] = dict(count=len(group[key]), ids=sorted(group[key]), record_ids=sorted(group['records']),
                               denominator=len(universe), unit=key)
        result['records'] = metric(group['records'])
        return result

    return dict(schema='attention-summary/1', summary_rules_version='record-union/1',
                analysis_id=state.get('analysis_id'), revision=state.get('revision'), saved=True,
                rules_version=state.get('rules_version'), a_version=reference.get('version'),
                material_status=state.get('material_status'), a_material_status=state.get('a_material_status'),
                b_material_status=state.get('b_material_status'), filters=deepcopy(filters),
                denominator=metric(universe), hits=metric(groups['content']['records'] | groups['disposition']['records']),
                content=auxiliary(groups['content']), disposition=auxiliary(groups['disposition']),
                directions={k: metric(v) for k,v in directions.items()}, statuses={k: metric(v) for k,v in statuses.items()},
                outside={k: metric(v) for k,v in outside.items()},
                relations={k: metric(v) for k,v in relations.items()}, relation_details=relation_details,
                details=details, contributions=contributions, theme_definitions=deepcopy(themes), a_reference=deepcopy(reference),
                themes={t: metric(s) for t, s in theme_sets.items()},
                a_items={a: {k: metric(s) for k,s in kinds.items()} for a,kinds in item_sets.items()},
                a_parts={p: {k: metric(s) for k,s in kinds.items()} for p,kinds in part_sets.items()},
                a_unassigned={k: metric(s) for k,s in unassigned.items()})
