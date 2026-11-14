"""Evidence-linked positions, separate from canonical saved coverage counts.

Consumes summarize() output, including its selected contribution set. Suggested
targets retain their names, but never acquire confirmed coverage by projection.
"""
from copy import deepcopy

_INACTIVE = {'withdrawn', 'superseded'}


def project_positions(summary):
    """Return an independent JSON-safe position model for a saved summary."""
    reference = summary['a_reference']
    items = {a['id']: a for a in reference.get('items', [])}
    parts = {a['id']: a for a in reference.get('parts', [])}
    regions = [dict(id='item:' + aid, kind='item', item_id=aid,
                    part_id=a.get('part_id'), label=a.get('text', aid),
                    part_label=parts.get(a.get('part_id'), {}).get('label', '未分部分'))
               for aid, a in items.items()]
    regions.extend(dict(id=k, kind=k, label=label) for k, label in [
        ('outside', '当前参照未明示 / 清单外'), ('pending', '位置待核 / 暂未定'),
        ('absent', '未导入A'), ('stale', '旧A或来源失效：须重新核对'),
        ('disposition', '流程或总体处置（单列）')])
    placements = []
    stale_source = ((summary.get('a_material_status') or summary.get('material_status')) == 'needs_revalidation'
                    or summary.get('b_material_status') == 'needs_revalidation')
    for c in summary['contributions']:
        f = next(e['facet'] for e in summary['details'][c['record_id']]['facets']
                 if e['facet']['facet_id'] == c['facet_id'])
        common = {k: c[k] for k in ('record_id', 'opinion_id', 'facet_id')}
        common.update(label=f['interpretation'], facet_status=c['status'],
                      directions=deepcopy(c['directions']), expression=deepcopy(c['expression']))

        def put(region, link=None, pending=False, reason=None):
            link = link or {}
            placements.append(dict(common, region_id=region,
                                   proposed_kind=link.get('kind'),
                                   review_status='needs_review' if pending else link.get('status', c['status']),
                                   reason=reason or link.get('reason', ''),
                                   scope=link.get('scope', ''), version=link.get('version'),
                                   evidence=deepcopy(link.get('evidence', f.get('evidence', [])))))

        if c['kind'] != 'content':
            put('disposition')
            continue
        if not items:
            put('absent', reason='未导入A；不能判为清单外')
            continue
        linked = False; pending_seen = False
        for link in f.get('a_links', []):
            if link.get('status') in _INACTIVE:
                continue
            linked = True
            aid = link.get('a_item_id')
            if stale_source or link.get('version') != reference.get('version') or (aid is not None and aid not in items):
                put('stale', link, True, '旧版本、失效来源或目标已不存在；原目标：' + str(aid))
                continue
            pending = (c['status'] == 'needs_review' or link.get('status') not in {'working', 'confirmed'}
                       or link.get('kind') == 'undetermined' or aid is None)
            if aid in items:
                put('item:' + aid, link, pending)
            if pending and not pending_seen:
                put('pending', link, True); pending_seen = True
        for outside in f.get('outside', []):
            if outside.get('status') in _INACTIVE:
                continue
            linked = True
            if stale_source:
                put('stale', outside, True, '来源失效，清单外判断须重核')
            else:
                put('outside', outside, c['status'] == 'needs_review' or outside.get('status') == 'needs_review')
        if not linked:
            put('pending', pending=True, reason='尚无位置判断；不等于清单外')
    return dict(schema='attention-positions/1', analysis_id=summary['analysis_id'],
                revision=summary['revision'], a_version=summary['a_version'],
                denominator=deepcopy(summary['denominator']), regions=regions, placements=placements)
