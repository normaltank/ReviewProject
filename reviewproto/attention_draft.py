"""Explicit, conservative Adapter for working-attention-index-v1, never gold."""
import copy
import uuid

from .core import digest, require
from .attention_model import text


def prepare(draft):
    require(isinstance(draft, dict) and draft.get('schema') == 'working-attention-index-v1', 'E_ATTENTION_DRAFT_SCHEMA')
    require(isinstance(draft.get('records'), list) and isinstance(draft.get('themes'), list), 'E_ATTENTION_DRAFT_SCHEMA')
    aliases, lookup = [], {}

    def identity(kind, alias):
        text(alias)
        require((kind, alias) not in lookup, 'E_ATTENTION_DUPLICATE')
        ident = kind + '-' + uuid.uuid4().hex
        lookup[kind, alias] = ident
        aliases.append({'kind': kind, 'alias': alias, 'id': ident, 'disposition': 'migrated_working'})
        return ident

    payload = {'schema': 'attention-input/1', 'records': [], 'a_reference': {'version': 'not-yet-imported', 'items': []}}
    themes = []
    for theme in draft['themes']:
        themes.append({'theme_id': identity('theme', theme['id']), 'label': text(theme['label']), 'definition': text(theme['definition']), 'parent_ids': [], 'status': 'working', 'legacy_aliases': [theme['id']]})
    for record in draft['records']:
        require(record.get('visibility', 'visibility_unknown') in {'author_visible', 'visibility_unknown'}, 'E_ATTENTION_PRIVATE')
        raw = text(record['original_visible_text'])
        require(digest(raw.encode('utf-8')) == record['original_text_sha256'], 'E_ATTENTION_DRAFT_HASH')
        # record identity is assigned by the frozen-source Adapter, never by draft position.
        payload['records'].append({'anchor': text(record['id']), 'visibility': 'visibility_unknown', 'text': raw, 'scores': copy.deepcopy(record['scores']), 'locator': {'working_record': record['id'], 'paper_id': record.get('paper_id', ''), 'coordinate_basis': 'original_visible_text Unicode codepoints; ordinary transcription'}})
        for facet in record['facets']:
            identity('facet', facet['id'])
    return payload, themes, aliases, lookup


def objects(draft, state, themes, aliases, lookup):
    edits, relations = [], []
    records = {r['anchor']: r for r in state['records']}
    require(len(records) == len(draft['records']), 'E_ATTENTION_DUPLICATE')
    for old in draft['records']:
        record = records[old['id']]
        record['legacy_aliases'] = [old['id']]
        record['expression_note'] = old.get('expression_function', '')
        record['score_role_note'] = old.get('score_role', '')
        aliases.append({'kind': 'record', 'alias': old['id'], 'id': record['record_id'], 'disposition': 'migrated_working'})
        def ev(value):
            require(isinstance(value, dict), 'E_ATTENTION_EVIDENCE')
            return {'source_id': record['source_id'], 'section_id': record['anchor'], 'start': value['start'], 'end': value['end'], 'quote': value['quote']}
        for facet in old['facets']:
            evidence = [ev(facet['evidence'])]
            fid = lookup['facet', facet['id']]
            members = []
            for alias in facet['themes']:
                require(('theme', alias) in lookup, 'E_ATTENTION_THEME')
                members.append({'theme_id': lookup['theme', alias], 'reason': '沿用工作稿成员解释：' + facet['focus'], 'evidence': evidence, 'status': 'working'})
            edits.append({'opinion_id': 'op-' + uuid.uuid4().hex, 'record_id': record['record_id'], 'interpretation': facet['focus'], 'status': 'working', 'facets': [{'facet_id': fid, 'interpretation': facet['focus'], 'evidence': evidence, 'themes': members, 'status': 'working', 'legacy_aliases': [facet['id']]}]})
        for index, relation in enumerate(old.get('local_relations', []), 1):
            alias = old['id'] + ':relation:' + str(index)
            rid = 'relation-' + uuid.uuid4().hex
            aliases.append({'kind': 'relation', 'alias': alias, 'id': rid, 'disposition': 'migrated_needs_review'})
            endpoints = []
            for alias_facet in relation['facet_ids']:
                require(('facet', alias_facet) in lookup, 'E_ATTENTION_RELATION')
                endpoints.append({'facet_id': lookup['facet', alias_facet], 'role': '旧稿范围成员（角色待核）'})
            relations.append({'relation_id': rid, 'type': relation['type'], 'endpoints': endpoints, 'direction': '未决，不从成员顺序推方向', 'scope': relation['working_reading'], 'evidence': [ev(relation['evidence'])], 'reading': relation['working_reading'], 'ambiguity': '显式迁入旧工作解释；端点角色、方向及作用范围须逐条核对，原“或”不推排他或因果。', 'status': 'needs_review', 'legacy_aliases': [alias]})
    state['legacy_aliases'] = aliases
    return {'edits': edits, 'themes': themes, 'relations': relations}
