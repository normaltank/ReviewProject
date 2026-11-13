"""Read-only review navigation: identity-only links and uncovered source spans."""
from pathlib import Path
from urllib.parse import urlencode
from html import escape
import heapq

from .core import require


def editor_fragment(source, *, candidate_id=None, section_id=None, start=None, end=None):
    parameters = dict(source_id=source['source']['source_id'], base_revision=source['revision'])
    if candidate_id is not None:
        parameters['candidate_id'] = candidate_id
    else:
        parameters.update(section_id=section_id, start=start, end=end)
    return '#editor?' + urlencode(parameters)


def editor_link(source, **target):
    return (Path(source['workspace']) / 'report.html').as_uri() + editor_fragment(source, **target)


def text_range(gap):
    return any(char.isalnum() for char in gap['quote'])


def main_quote_overlaps(source, limit=200):
    """Bounded interval containment hints, never a semantic duplicate decision.

    A max-end heap costs O(n log n + limit log n), even when many intervals
    cross without containment. Only the first (main) evidence is considered.
    """
    require(type(limit) is int and 1 <= limit <= 200, 'E_OVERLAP_LIMIT')
    ordinary = {s['section_id'] for s in source['sections'] if s['visibility'] in {'author_visible', 'visibility_unknown'}}
    groups = {}
    for order, entry in enumerate(source['candidates']):
        candidate = entry['value']
        if candidate['section_id'] not in ordinary or candidate['status'] in {'rejected', 'withdrawn', 'superseded'}:
            continue
        main = candidate['evidence'][0]
        if main.get('source_id') != source['source']['source_id'] or main.get('section_id') != candidate['section_id']:
            continue
        groups.setdefault(candidate['section_id'], []).append((main['start'], -main['end'], order, candidate))
    result = []
    for sid, intervals in groups.items():
        heap = []
        for _, negative_end, order, candidate in sorted(intervals):
            end, containers = -negative_end, []
            while heap and -heap[0][0] >= end:
                item = heapq.heappop(heap)
                containers.append(item)
                other = item[2]
                if other['candidate_id'] != candidate['candidate_id']:
                    result.append(dict(section_id=sid, left=other, right=candidate))
                    if len(result) == limit:
                        return result, True
            for item in containers:
                heapq.heappush(heap, item)
            heapq.heappush(heap, (negative_end, order, candidate))
    return result, False


def render_overlap_panel(source, *, local=False):
    pairs, limited = main_quote_overlaps(source)
    esc = lambda value: escape(str(value), quote=True)
    parts = [f'<details class="quote-overlaps"><summary>引文重合，需复核 · 展示 {len(pairs)} 对</summary>',
             '<p>仅比较同一普通分区的主引文坐标相同或包含；共享理由不作为重复依据。方向或动作不同仍可能是独立观点，不自动合并、撤回或确认。</p>']
    if limited:
        parts.append(f'<p class="overlap-limit">仅展示前 {len(pairs)} 对，仍需继续复核；未展示不表示已排除其他重合。</p>')
    for pair in pairs:
        parts.append(f'<div class="overlap-pair" data-left="{esc(pair["left"]["candidate_id"])}" data-right="{esc(pair["right"]["candidate_id"])}">')
        for label in ('left', 'right'):
            candidate = pair[label]
            evidence = candidate['evidence'][0]
            link = editor_fragment(source, candidate_id=candidate['candidate_id']) if local else editor_link(source, candidate_id=candidate['candidate_id'])
            target = ' target="_blank" rel="noopener"' if local else ''
            parts.append(f'<p>{esc(candidate["candidate_id"])} · {esc(pair["section_id"])} [{evidence["start"]}, {evidence["end"]}) · 方向 {esc(candidate["direction"])} · <a class="overlap-correction" data-candidate="{esc(candidate["candidate_id"])}" href="{esc(link)}"{target}>在新表单纠正此观点</a></p><pre>{esc(evidence["quote"][:180])}{"…（原文预览，完整证据请打开表单）" if len(evidence["quote"]) > 180 else ""}</pre>')
        parts.append('</div>')
    if not pairs:
        parts.append('<p>本次所选主引文未发现可展示的相同或包含；不等于没有语义重复。</p>')
    parts.append('</details>')
    return ''.join(parts)


def unreferenced_ranges(source, section, *, include_whitespace=False):
    """Complement of all selected evidence; no claim of semantic omission."""
    if section['visibility'] not in {'author_visible', 'visibility_unknown'}:
        return []
    text = section['text']
    spans = []
    for entry in source['candidates']:
        candidate = entry['value']
        if candidate['section_id'] != section['section_id']:
            continue
        for evidence in candidate['evidence']:
            start, end = evidence['start'], evidence['end']
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                    and text[start:end] == evidence['quote'], 'E_BATCH_EVIDENCE')
            spans.append((start, end))
    cursor, gaps = 0, []
    for start, end in sorted(spans):
        if start > cursor and (include_whitespace or text[cursor:start].strip()):
            gaps.append(dict(start=cursor, end=start, quote=text[cursor:start]))
        cursor = max(cursor, end)
    if cursor < len(text) and (include_whitespace or text[cursor:].strip()):
        gaps.append(dict(start=cursor, end=len(text), quote=text[cursor:]))
    return gaps
