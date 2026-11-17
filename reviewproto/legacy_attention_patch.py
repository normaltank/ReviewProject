"""Historical attention-patch/1 conversion; never rewrites its audit identity."""
import copy
from .core import require


def apply_legacy_patch(state, patch):
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

