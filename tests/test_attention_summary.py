"""Independent hand-calculated record sets from the T4 four-record oracle."""
import copy
import unittest
import os
import tempfile
from pathlib import Path

from reviewproto.attention_summary import summarize


def oracle_state():
    def link(item, kind='explicit', **extra):
        return dict(a_item_id=item, version='synthetic-A', kind=kind,
                    status='working', scope='合成范围', reason='合成依据', evidence=[], **extra)

    def facet(fid, themes, links, **extra):
        return dict(facet_id=fid, kind='content', status='working',
                    interpretation='合成解释', evidence=[],
                    themes=[dict(theme_id=t, status='working') for t in themes],
                    a_links=links, outside=[], expression={}, qualifiers={}, **extra)

    f1 = facet('f1', ['T1'], [link('A1'), link('A2')])
    f2 = facet('f2', ['T2'], [link('A3', 'partial')])
    f3 = facet('f3', ['T1'], [link('A1'), link('A1', 'related'), link('A4')])
    f3['expression'] = dict(function='评价', boilerplate_candidate=True)
    f3['qualifiers'] = dict(direction='肯定')
    f4 = facet('f4', ['T2'], [link('A1', 'undetermined')])
    f4['outside'] = [dict(scope='清单外', status='working')]
    old = facet('old', ['T1'], [link('A2')]); old['status'] = 'superseded'
    disposition = facet('decision', ['T1'], [link('A2')]); disposition['kind'] = 'disposition'
    opinions = [dict(opinion_id='o1', record_id='r1', status='working', facets=[f1, f2]),
                dict(opinion_id='o2', record_id='r2', status='working', facets=[f3]),
                dict(opinion_id='o3', record_id='r3', status='needs_review', facets=[f4, old, disposition])]
    return dict(schema='attention/1', analysis_id='synthetic', revision=7, rules_version='test-rules',
                records=[dict(record_id=r, text='合成原话', locator={'paper_id': p}, scores=[])
                         for r, p in [('r1', 'p1'), ('r2', 'p1'), ('r3', 'p2'), ('r4', None)]],
                opinions=opinions,
                themes=[dict(theme_id=t, label=t, definition='合成主题', status='working', parent_ids=parents)
                        for t, parents in [('ROOT', []), ('T1', ['ROOT']), ('T2', ['ROOT'])]],
                a_reference=dict(version='synthetic-A', parts=[dict(id=p, label=p) for p in ['P1', 'P2']],
                                 items=[dict(id=a, text=a, part_id=p) for a,p in [('A1','P1'),('A2','P1'),('A3','P2'),('A4','P2')]]),
                relations=[dict(relation_id='condition', type='conditional_fallback', status='working',
                                endpoints=[dict(facet_id='f1'),dict(facet_id='decision')], scope='条件动作'),
                           dict(relation_id='reason', type='reason', status='working',
                                endpoints=[dict(facet_id='f3')], scope='理由链')])


class AttentionSummary(unittest.TestCase):
    def test_saved_workspace_correction_reopen_updates_summary_without_draft_effect(self):
        from reviewproto.attention import AttentionWorkspace
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'analysis'
            ws = AttentionWorkspace(path)
            try:
                saved = ws.build(dict(schema='attention-input/1', records=[dict(anchor='synthetic', visibility='visibility_unknown', text='合成原话', scores=[])], a_reference=dict(version='synthetic', items=[])))
                record = saved['records'][0]
                ev = dict(source_id=record['source_id'], section_id='synthetic', start=0, end=4, quote='合成原话')
                facet = dict(facet_id='saved-f', kind='content', status='working', interpretation='合成解释', evidence=[ev], qualifiers=dict(direction='肯定'))
                patch = dict(schema='attention-patch/2', analysis_id=saved['analysis_id'], base_revision=0, actor='合成编辑', reason='合成核对', edits=[dict(opinion_id='saved-o', record_id=record['record_id'], status='working', interpretation='合成解释', facets=[facet])])
                self.assertEqual(summarize(ws.state())['hits']['count'], 0)
                ws.apply(patch)
                first = summarize(ws.state())
                self.assertEqual(first['revision'], 1)
                self.assertEqual(first['directions']['肯定']['record_ids'], [record['record_id']])
                correction = copy.deepcopy(patch); correction['base_revision'] = 1
                correction['edits'][0]['facets'][0]['qualifiers']['direction'] = '建议'
                self.assertEqual(summarize(ws.state())['directions']['肯定']['count'], 1)
                ws.apply(correction)
            finally:
                ws.close()
            reopened = AttentionWorkspace(path)
            try:
                recovered = summarize(reopened.recover())
                self.assertEqual(recovered['revision'], 2)
                self.assertEqual(recovered['directions']['建议']['record_ids'], [record['record_id']])
                self.assertNotIn('肯定', recovered['directions'])
                self.assertEqual(first['directions']['肯定']['count'], 1)
            finally:
                reopened.close()

    def test_withdrawn_links_and_unmatched_relations_do_not_count_or_guess_identity(self):
        state = oracle_state()
        same_words = copy.deepcopy(state['records'][0]); same_words['record_id'] = 'separate-source'
        state['records'].append(same_words)
        f = state['opinions'][1]['facets'][0]
        f['a_links'][0]['status'] = 'withdrawn'
        f['themes'][0]['status'] = 'withdrawn'
        actual = summarize(state)
        self.assertEqual(actual['denominator']['count'], 5)
        self.assertEqual(actual['themes']['T1']['record_ids'], ['r1'])
        self.assertEqual(actual['a_items']['A1']['explicit']['record_ids'], ['r1'])
        filtered = summarize(state, {'boilerplate_candidate': True})
        self.assertEqual(filtered['relations']['conditional_fallback']['record_ids'], [])
        self.assertEqual(filtered['relations']['conditional_fallback']['denominator'], 5)
        self.assertEqual(filtered['relation_details'][0]['relation_id'], 'reason')

    def test_browser_readable_record_hits_keyboard_narrow_and_no_active_markup(self):
        from playwright.sync_api import sync_playwright
        from reviewproto.attention_summary_view import render_summary
        state = oracle_state()
        state['records'][1]['text'] = '<img src=x onerror="alert(1)">合成原话'
        summary = summarize(state, {'boilerplate_candidate': True})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'summary.html'
            path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + render_summary(summary) + '</html>', encoding='utf-8')
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY', 'C:/Program Files/Google/Chrome/Application/chrome.exe'), headless=True)
                page = browser.new_page(offline=True, viewport={'width': 1440, 'height': 1000})
                page.goto(path.as_uri())
                self.assertIn('已保存修订 7', page.locator('.attention-summary').inner_text())
                self.assertIn('分母 4 条评语记录', page.locator('.attention-summary').inner_text())
                self.assertEqual(page.locator('img, script').count(), 0)
                hit = page.get_by_role('link', name='r2', exact=True).first
                hit.focus(); page.keyboard.press('Enter')
                self.assertIn('r2', page.locator(':target').inner_text())
                detail = page.locator(':target')
                detail.locator('summary').focus(); page.keyboard.press('Enter')
                self.assertIn('<img src=x', detail.inner_text())
                for width in [1440, 420]:
                    page.set_viewport_size({'width': width, 'height': 1000})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    evidence = os.environ.get('ATTENTION_SUMMARY_EVIDENCE_DIR')
                    if evidence:
                        Path(evidence).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(Path(evidence) / f'summary-{width}.png'), full_page=True)
                browser.close()

    def test_contribution_index_carries_effective_buckets_and_list_directions(self):
        state = oracle_state()
        state['opinions'][0]['facets'][0]['qualifiers']['direction'] = ['肯定', '建议']
        state['opinions'][0]['facets'][0]['a_links'][0]['status'] = 'needs_review'
        actual = summarize(state, {'directions': ['建议']})
        self.assertEqual(actual['directions']['建议']['record_ids'], ['r1'])
        self.assertEqual(actual['directions']['肯定']['record_ids'], ['r1'])
        c = actual['contributions'][0]
        self.assertEqual(c['theme_ids'], ['ROOT', 'T1'])
        self.assertEqual(c['a_items'], [{'id': 'A1', 'kind': 'needs_review'}, {'id': 'A2', 'kind': 'explicit'}])
        self.assertEqual(c['a_parts'], [{'id': 'P1', 'kind': 'needs_review'}, {'id': 'P1', 'kind': 'explicit'}])
        self.assertEqual(c['record_id'], 'r1')
        self.assertEqual(c['facet_id'], 'f1')

    def test_details_auxiliary_and_relations_stay_separate_and_input_unchanged(self):
        state = oracle_state(); before = copy.deepcopy(state)
        state['opinions'][0]['facets'][0]['a_links'].append(dict(a_item_id=None, kind='undetermined', version='synthetic-A', status='working'))
        before = copy.deepcopy(state)
        actual = summarize(state)
        self.assertEqual(state, before)
        self.assertEqual(actual['content']['opinions']['count'], 3)
        self.assertEqual(actual['content']['facets']['count'], 4)
        self.assertEqual(actual['content']['facets']['record_ids'], ['r1', 'r2', 'r3'])
        self.assertEqual(actual['disposition']['facets']['count'], 1)
        self.assertEqual(actual['disposition']['facets']['record_ids'], ['r3'])
        self.assertEqual(actual['relations']['conditional_fallback']['record_ids'], ['r1', 'r3'])
        self.assertEqual(actual['relations']['reason']['record_ids'], ['r2'])
        self.assertEqual(actual['a_unassigned']['undetermined']['record_ids'], ['r1'])
        self.assertEqual(actual['outside']['working']['record_ids'], ['r3'])
        self.assertEqual(actual['directions']['肯定']['record_ids'], ['r2'])
        self.assertEqual(actual['revision'], 7)
        self.assertEqual(actual['details']['r2']['record']['text'], '合成原话')
        self.assertEqual(actual['details']['r2']['facets'][0]['facet']['facet_id'], 'f3')
        self.assertEqual(actual['details']['r4']['facets'], [])

    def test_recheck_invalid_reference_and_legacy_ungrouped_are_not_explicit(self):
        state = oracle_state()
        f = state['opinions'][0]['facets'][0]
        f['a_links'][0]['status'] = 'needs_review'
        f['a_links'][1]['version'] = 'old-A'
        f['a_links'].append(dict(a_item_id='missing', version='synthetic-A', kind='explicit', status='working'))
        actual = summarize(state)
        self.assertEqual(actual['a_items']['A1']['explicit']['record_ids'], ['r2'])
        self.assertEqual(actual['a_items']['A1']['needs_review']['record_ids'], ['r1'])
        self.assertEqual(actual['a_items']['A2']['explicit']['record_ids'], [])
        self.assertEqual(actual['a_items']['A2']['needs_review']['record_ids'], ['r1'])
        self.assertEqual(actual['a_unassigned']['needs_review']['record_ids'], ['r1'])
        state['a_material_status'] = 'needs_revalidation'
        self.assertEqual(summarize(state)['a_items']['A1']['explicit']['record_ids'], [])
        state['a_reference'].pop('parts')
        for item in state['a_reference']['items']:
            item.pop('part_id')
        self.assertEqual(summarize(state)['a_parts'], {})

    def test_expression_filters_keep_denominator_and_zero_rows(self):
        state = oracle_state()
        actual = summarize(state, {'boilerplate_candidate': True})
        self.assertEqual(actual['denominator']['count'], 4)
        self.assertEqual(actual['themes']['T1']['record_ids'], ['r2'])
        self.assertEqual(actual['themes']['T2']['record_ids'], [])
        self.assertEqual(actual['a_parts']['P1']['explicit']['record_ids'], ['r2'])
        self.assertEqual(actual['a_parts']['P2']['explicit']['record_ids'], ['r2'])
        zero = summarize(state, {'directions': ['没有的方向']})
        self.assertEqual(zero['themes']['T1']['count'], 0)
        self.assertEqual(zero['themes']['T1']['denominator'], 4)
        self.assertEqual(summarize(state, {'paper_ids': ['p1']})['denominator']['record_ids'], ['r1', 'r2'])
        selected = summarize(state, {'record_ids': ['r3', 'r4']})
        self.assertEqual(selected['a_items']['A1']['undetermined']['record_ids'], ['r3'])
        self.assertEqual(selected['a_items']['A1']['explicit']['record_ids'], [])
        empty = summarize(state, {'record_ids': []})
        self.assertEqual(empty['themes']['T1']['denominator'], 0)
        self.assertIsNone(empty['themes']['T1']['ratio'])

    def test_record_union_is_not_sum_and_ignores_disposition_and_superseded(self):
        state = oracle_state()
        state['records'].append(copy.deepcopy(state['records'][0]))
        state['opinions'].append(copy.deepcopy(state['opinions'][0]))
        actual = summarize(state)
        self.assertEqual(actual['denominator']['record_ids'], ['r1', 'r2', 'r3', 'r4'])
        self.assertEqual(actual['themes']['T1']['record_ids'], ['r1', 'r2'])
        self.assertEqual(actual['themes']['T2']['record_ids'], ['r1', 'r3'])
        self.assertEqual(actual['themes']['ROOT']['record_ids'], ['r1', 'r2', 'r3'])
        self.assertEqual(actual['a_parts']['P1']['explicit']['record_ids'], ['r1', 'r2'])
        self.assertEqual(actual['a_parts']['P2']['explicit']['record_ids'], ['r2'])
        self.assertEqual(actual['a_parts']['P2']['partial']['record_ids'], ['r1'])
        self.assertEqual(actual['a_items']['A1']['explicit']['record_ids'], ['r1', 'r2'])
        self.assertEqual(actual['a_items']['A1']['related']['record_ids'], ['r2'])
        self.assertEqual(actual['a_items']['A1']['undetermined']['record_ids'], ['r3'])
        self.assertEqual(actual['a_items']['A2']['explicit']['record_ids'], ['r1'])


if __name__ == '__main__':
    unittest.main()
