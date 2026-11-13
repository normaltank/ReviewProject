"""Explicit A reference versions and evidence-grounded associations."""
import copy
from pathlib import Path
from .core import require, digest
from .batch import checked_local
from .store import read_input
from .framework import load_json


def validate_reference(ref):
    from .attention_model import text
    require(isinstance(ref, dict) and set(ref) <= {'version', 'parts', 'items'}, 'E_ATTENTION_A')
    text(ref.get('version'))
    parts = ref.get('parts', [])
    require(isinstance(parts, list) and isinstance(ref.get('items'), list), 'E_ATTENTION_A')
    pids, ids = set(), set()
    for part in parts:
        require(isinstance(part, dict) and set(part) == {'id', 'label'}, 'E_ATTENTION_A')
        text(part['id']); text(part['label'])
        require(part['id'] not in pids, 'E_ATTENTION_A'); pids.add(part['id'])
    for item in ref['items']:
        require(isinstance(item, dict) and set(item) <= {'id', 'text', 'locator', 'part_id'}, 'E_ATTENTION_A')
        for key in ('id', 'text', 'locator'): text(item.get(key))
        require(item['id'] not in ids and (item.get('part_id') in pids if parts or 'part_id' in item else True), 'E_ATTENTION_A')
        ids.add(item['id'])


def validate_links(state, record, facet, old):
    from .attention_model import text, evidence, STATUSES
    ref = state['a_reference']
    for field in ('a_links', 'outside'):
        require(isinstance(facet[field], list), 'E_ATTENTION_A')
        for link in facet[field]:
            keys = {'scope', 'reason', 'evidence', 'status'} | ({'a_item_id', 'version', 'kind'} if field == 'a_links' else set())
            require(isinstance(link, dict) and set(link) == keys, 'E_ATTENTION_A')
            text(link['scope']); text(link['reason']); evidence(record, link['evidence'])
            require(link['status'] in STATUSES, 'E_ATTENTION_STATUS')
            if field == 'a_links':
                require(link['kind'] in {'explicit', 'partial', 'related', 'undetermined'}, 'E_ATTENTION_A_KIND')
                known = any(i['id'] == link['a_item_id'] for i in ref['items'])
                current = link['version'] == ref['version'] and (known or link['kind'] == 'undetermined' and link['a_item_id'] is None)
                retained = old and any(dict(x, status=link['status']) == link for x in old.get(field, [])) and link['status'] in {'needs_review', 'withdrawn'}
                require(current or retained, 'E_ATTENTION_A_VERSION')


def prepare_import(path, state, actor, reason):
    path = checked_local(path)
    raw = read_input(path, 10_000_000, 'E_ATTENTION_LIMIT')
    payload = load_json(raw)
    require(isinstance(payload, dict) and payload.get('schema') == 'attention-a-input/1' and set(payload) <= {'schema','a_reference','source'}, 'E_ATTENTION_A')
    validate_reference(payload.get('a_reference'))
    bindings = [{'kind':'file','role':'a_reference','path':str(path),'fingerprint':digest(raw)}]
    if 'source' in payload:
        source = payload['source']
        require(isinstance(source, dict) and set(source) == {'path','fingerprint'}, 'E_ATTENTION_A_SOURCE')
        source_path = checked_local(path.parent / source['path'])
        require(digest(read_input(source_path, 10_000_000, 'E_ATTENTION_LIMIT')) == source['fingerprint'], 'E_ATTENTION_A_SOURCE')
        bindings.append(dict(source, kind='file', role='a_reference', path=str(source_path)))
    return dict(schema='attention-a-patch/1', analysis_id=state['analysis_id'],base_revision=state['revision'],actor=actor,reason=reason,a_reference=payload['a_reference'],bindings=bindings)


def apply_reference(state, patch):
    from .attention_model import project
    require(set(patch) == {'schema','analysis_id','base_revision','actor','reason','a_reference','bindings'}, 'E_ATTENTION_PATCH')
    ref = patch['a_reference']; validate_reference(ref)
    require(ref['items'], 'E_ATTENTION_A_VERSION')
    for old in [state['a_reference']] + [h['a_reference'] for h in state.get('a_reference_history', [])]:
        require(old['version'] != ref['version'] or old == ref, 'E_ATTENTION_A_VERSION')
    require(isinstance(patch['bindings'], list) and patch['bindings'], 'E_ATTENTION_A_SOURCE')
    for b in patch['bindings']:
        require(isinstance(b, dict) and set(b) == {'kind','role','path','fingerprint'} and b['kind']=='file' and b['role']=='a_reference', 'E_ATTENTION_A_SOURCE')
        require(digest(read_input(checked_local(b['path']), 10_000_000, 'E_ATTENTION_LIMIT')) == b['fingerprint'], 'E_ATTENTION_A_SOURCE')
    state.setdefault('a_reference_history', []).append({'a_reference':copy.deepcopy(state['a_reference']), 'bindings':[b for b in state['bindings'] if b.get('role')=='a_reference'], 'replaced_at_revision':state['revision']+1})
    state['bindings'] = [b for b in state['bindings'] if b.get('role')!='a_reference'] + copy.deepcopy(patch['bindings'])
    state['a_reference'] = copy.deepcopy(ref)
    for op in state['opinions']:
        for f in op['facets']:
            for link in f['a_links']:
                if link['status'] != 'withdrawn': link['status']='needs_review'
        project(op)
