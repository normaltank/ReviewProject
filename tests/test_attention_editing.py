import copy
import tempfile
import unittest
from pathlib import Path

from reviewproto.attention import AttentionWorkspace


class AttentionEditing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ws = AttentionWorkspace(self.root / 'analysis')
        self.addCleanup(self.ws.close)
        self.state = self.ws.build({'schema': 'attention-input/1', 'records': [
            {'anchor': 'S1', 'visibility': 'visibility_unknown', 'text': '基本清晰😀。基本清晰😀。但证据并不充分。若不能补证，可降低结论；例如增加说明。', 'scores': [{'label': '原分', 'raw_value': ' 4.0 '}]}],
            'a_reference': {'version': 'synthetic-a', 'items': []}})

    def evidence(self, start, end):
        r = self.state['records'][0]
        return {'source_id': r['source_id'], 'section_id': 'S1', 'start': start, 'end': end, 'quote': r['text'][start:end]}

    def facet(self, fid, text, start, end):
        return {'facet_id': fid, 'interpretation': text, 'evidence': [self.evidence(start, end)], 'status': 'working'}

    def patch(self, **fields):
        return dict(schema='attention-patch/2', analysis_id=self.state['analysis_id'], base_revision=self.ws.state()['revision'], actor='合成编辑', reason='根据原话纠正', **fields)

    def test_multiple_facets_keep_distinct_qualifiers_and_second_duplicate_evidence(self):
        first = self.facet('f-positive', '总体基本清晰', 6, 11)
        first['qualifiers'] = {'degree': '基本', 'direction': '肯定'}
        second = self.facet('f-negative', '证据并不充分', 12, 20)
        second['qualifiers'] = {'negation': '并不', 'direction': '否定'}
        self.ws.apply(self.patch(edits=[{'opinion_id': 'op-compound', 'record_id': self.state['records'][0]['record_id'], 'interpretation': '总体与局部并存', 'status': 'working', 'facets': [first, second]}]))
        self.ws.close()
        self.ws = AttentionWorkspace(self.root / 'analysis')
        self.addCleanup(self.ws.close)
        saved = self.ws.recover()
        facets = saved['opinions'][0]['facets']
        self.assertEqual([f['facet_id'] for f in facets], ['f-positive', 'f-negative'])
        self.assertEqual(facets[0]['evidence'][0]['start'], 6)
        self.assertEqual(facets[0]['qualifiers']['degree'], '基本')
        self.assertEqual(facets[1]['qualifiers']['negation'], '并不')
        self.assertEqual(saved['records'][0]['scores'], [{'label': '原分', 'raw_value': ' 4.0 '}])

    def test_t1_patch_targets_explicit_facet_in_compound_opinion_and_bad_patch_is_atomic(self):
        from reviewproto.core import ReviewError
        record = self.state['records'][0]['record_id']
        self.ws.apply(self.patch(edits=[{'opinion_id': 'op-two', 'record_id': record, 'interpretation': '相反方向的不同范围', 'status': 'working', 'facets': [self.facet('f-first', '总体清晰', 0, 5), self.facet('f-second', '局部不充分', 12, 20)]}]))
        legacy = dict(self.patch(edits=[{'opinion_id': 'op-two', 'facet_id': 'f-second', 'record_id': record, 'interpretation': '局部证据并不充分', 'status': 'working', 'evidence': [self.evidence(12, 20)]}]), schema='attention-patch/1')
        self.ws.apply(legacy)
        self.assertEqual([f['interpretation'] for f in self.ws.state()['opinions'][0]['facets']], ['总体清晰', '局部证据并不充分'])
        bad = copy.deepcopy(legacy); bad['base_revision'] = 2; bad['edits'][0]['facet_id'] = 'unknown'
        with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_IDENTITY'):
            self.ws.apply(bad)
        self.assertEqual(self.ws.state()['revision'], 2)
        relation = {'relation_id': 'invalid', 'type': 'reason', 'endpoints': [{'facet_id': 'missing', 'role': '理由'}], 'direction': '理由到判断', 'scope': '合成局部', 'reading': '工作读法', 'ambiguity': '', 'evidence': [self.evidence(12, 20)], 'status': 'working'}
        with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_RELATION'):
            self.ws.apply(self.patch(themes=[{'theme_id': 't', 'label': '不应部分保存', 'definition': '合成', 'parent_ids': [], 'status': 'working'}], relations=[relation]))
        self.assertEqual(self.ws.state()['themes'], [])
        self.assertEqual(self.ws.state()['revision'], 2)

    def test_theme_rename_and_facet_reorder_preserve_identity_definition_change_is_reviewable(self):
        record = self.state['records'][0]['record_id']
        op = {'opinion_id': 'op-two', 'record_id': record, 'interpretation': '不同范围并存', 'status': 'working', 'facets': [self.facet('f-first', '清晰', 0, 5), self.facet('f-second', '不充分', 12, 20)]}
        themes = [{'theme_id': 't1', 'label': '表达', 'definition': '表达组织', 'parent_ids': [], 'status': 'working'}, {'theme_id': 't2', 'label': '证据', 'definition': '证据承载', 'parent_ids': [], 'status': 'working'}]
        self.ws.apply(self.patch(edits=[op], themes=themes))
        op['facets'].reverse(); themes.reverse(); themes[1]['label'] = '表达组织'
        saved = self.ws.apply(self.patch(edits=[op], themes=themes))
        self.assertEqual([f['facet_id'] for f in saved['opinions'][0]['facets']], ['f-second', 'f-first'])
        self.assertEqual({t['theme_id']: t['label'] for t in saved['themes']}, {'t1': '表达组织', 't2': '证据'})
        self.assertEqual(saved['themes'][0]['version'], 1)
        changed = dict(themes[1], definition='范围扩至图表组织', status='confirmed')
        revised = self.ws.apply(self.patch(themes=[changed]))
        self.assertEqual(revised['themes'][0]['theme_id'], 't1')
        self.assertEqual(revised['themes'][0]['version'], 2)
        self.assertEqual(revised['themes'][0]['status'], 'needs_review')

    def test_changed_theme_definition_marks_existing_membership_for_review(self):
        f = self.facet('f1', '总体肯定', 0, 5)
        f['themes'] = [{'theme_id': 't', 'reason': '直接评价清晰', 'evidence': f['evidence'], 'status': 'confirmed'}]
        theme = {'theme_id': 't', 'label': '表达', 'definition': '表达清晰程度', 'parent_ids': [], 'status': 'confirmed'}
        self.ws.apply(self.patch(edits=[{'opinion_id': 'op', 'record_id': self.state['records'][0]['record_id'], 'interpretation': '总体清晰', 'status': 'working', 'facets': [f]}], themes=[theme]))
        theme['definition'] = '表达清晰程度及证据承载'
        saved = self.ws.apply(self.patch(themes=[theme]))
        self.assertEqual(saved['opinions'][0]['facets'][0]['themes'][0]['status'], 'needs_review')

    def test_split_and_merge_keep_lineage_and_mark_old_associations_for_review(self):
        r = self.state['records'][0]['record_id']
        facet = self.facet('f-original', '条件备用动作与例示', 20, 39)
        facet['themes'] = [{'theme_id': 't-action', 'reason': '具体建议内容', 'evidence': facet['evidence'], 'status': 'working'}]
        facet['qualifiers'] = {'conditions': '若不能补证', 'actions': '可降低结论', 'examples': '例如增加说明'}
        original = {'opinion_id': 'op-original', 'record_id': r, 'interpretation': '建议动作组', 'status': 'working', 'facets': [facet]}
        relation = {'relation_id': 'rel-condition', 'type': 'conditional_fallback', 'endpoints': [{'facet_id': 'f-original', 'role': '条件下的备用动作'}], 'direction': '条件约束动作', 'scope': '只约束降低结论', 'evidence': facet['evidence'], 'reading': '不能补证时可降低结论，例示不是必做', 'ambiguity': '不推排他或反向逻辑', 'status': 'working'}
        self.ws.apply(self.patch(edits=[original], themes=[{'theme_id': 't-action', 'label': '建议内容', 'definition': '有关补充说明或结论尺度的具体建议', 'parent_ids': [], 'status': 'working'}], relations=[relation]))
        left = {'opinion_id': 'op-left', 'record_id': r, 'interpretation': '条件备用动作', 'status': 'working', 'facets': [self.facet('f-left', '备用动作', 20, 33)], 'replaces': ['op-original']}
        right = {'opinion_id': 'op-right', 'record_id': r, 'interpretation': '例示说明', 'status': 'working', 'facets': [self.facet('f-right', '例示', 33, 39)], 'replaces': ['op-original']}
        saved = self.ws.apply(self.patch(edits=[left, right]))
        old = saved['opinions'][0]
        self.assertEqual(old['status'], 'superseded')
        self.assertEqual(old['superseded_by'], ['op-left', 'op-right'])
        self.assertEqual(old['facets'][0]['themes'][0]['status'], 'needs_review')
        self.assertEqual(saved['relations'][0]['endpoints'][0]['facet_id'], 'f-original')
        self.assertEqual(saved['relations'][0]['status'], 'needs_review')
        self.assertEqual(saved['opinions'][1]['facets'][0]['themes'], [])
        self.assertEqual(old['facets'][0]['qualifiers']['conditions'], '若不能补证')
        merged = {'opinion_id': 'op-merged', 'record_id': r, 'interpretation': '合并组织保留两方面', 'status': 'needs_review', 'facets': [self.facet('f-merged-left', '备用动作', 20, 33), self.facet('f-merged-right', '例示', 33, 39)], 'replaces': ['op-left', 'op-right']}
        final = self.ws.apply(self.patch(edits=[merged]))
        self.assertEqual(final['opinions'][-1]['replaces'], ['op-left', 'op-right'])
        self.assertEqual([o['status'] for o in final['opinions'][:3]], ['superseded'] * 3)

    def test_explicit_working_draft_adapter_keeps_all_aliases_and_raw_scores(self):
        import json
        from reviewproto.core import digest
        text = '基本清晰😀。基本清晰😀。'
        draft = {'schema': 'working-attention-index-v1', 'records': [{'id': 'OLD-R', 'paper_id': 'synthetic-paper', 'original_visible_text': text, 'original_text_sha256': digest(text.encode()), 'scores': [{'label': '原分', 'raw_value': ' 4.0 '}], 'expression_function': '记录开头的概括认可候选，作用待核', 'facets': [{'id': 'OLD-F1', 'focus': '基本肯定', 'themes': ['OLD-T'], 'evidence': {'start': 6, 'end': 11, 'quote': '基本清晰😀', 'anchors': ['基本清晰😀']}, 'interpretation_status': 'working_reading'}], 'local_relations': [{'type': 'coexisting_readings', 'facet_ids': ['OLD-F1'], 'working_reading': '并存读法待核', 'evidence': {'start': 6, 'end': 11, 'quote': '基本清晰😀'}}]}], 'themes': [{'id': 'OLD-T', 'label': '总体清晰', 'definition': '清晰程度的判断', 'record_ids': ['OLD-R'], 'coverage': 99, 'denominator': 999}]}
        source = self.root / 'working.json'; source.write_text(json.dumps(draft), encoding='utf-8')
        target = AttentionWorkspace(self.root / 'migrated'); self.addCleanup(target.close)
        migrated = target.migrate_working_draft(source, actor='合成编辑', reason='迁入工作解释')
        self.assertEqual(len(migrated['records']), 1)
        self.assertEqual(migrated['records'][0]['visibility'], 'visibility_unknown')
        self.assertEqual(migrated['records'][0]['expression_note'], draft['records'][0]['expression_function'])
        facet = migrated['opinions'][0]['facets'][0]
        self.assertEqual(facet['evidence'][0]['start'], 6)
        self.assertEqual(facet['status'], 'working')
        self.assertIsNone(facet['expression']['boilerplate_candidate'])
        self.assertEqual(facet['expression']['function'], '')
        self.assertEqual({a['alias'] for a in migrated['legacy_aliases']}, {'OLD-R', 'OLD-F1', 'OLD-T', 'OLD-R:relation:1'})
        self.assertNotIn('coverage', migrated['themes'][0])
        self.assertEqual(source.read_text(encoding='utf-8'), json.dumps(draft))
        from reviewproto.core import ReviewError
        for case, code in [('private', 'E_ATTENTION_PRIVATE'), ('bad-quote', 'E_ATTENTION_QUOTE')]:
            bad = copy.deepcopy(draft)
            if case == 'private':
                bad['records'][0]['visibility'] = 'internal_only'
            else:
                bad['records'][0]['facets'][0]['evidence']['quote'] = '改写后并非原文'
            badfile = self.root / (case + '.json'); badfile.write_text(json.dumps(bad), encoding='utf-8')
            failed = AttentionWorkspace(self.root / case); self.addCleanup(failed.close)
            with self.assertRaisesRegex(ReviewError, code):
                failed.migrate_working_draft(badfile, actor='合成', reason='原子拒收验证')
            with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_EMPTY'):
                failed.state()
        from reviewproto.desktop import Controller
        controller = Controller()
        result = controller.migrate_attention(source, self.root / 'controller-migration', '合成编辑', '普通本机入口')
        self.assertEqual(result['revision'], 1)
        self.assertEqual(result['kind'], 'attention')
        self.assertIsNone(controller.path)
        source.write_text('{}', encoding='utf-8')
        self.assertEqual(target.recover()['material_status'], 'needs_revalidation')

    def test_twenty_synthetic_counterexample_annotations_survive_public_save_and_reopen(self):
        import json
        cases = json.loads((Path(__file__).parent / 'fixtures/synthetic_attention_cases.json').read_text(encoding='utf-8'))['cases']
        target = AttentionWorkspace(self.root / 'counterexamples'); self.addCleanup(target.close)
        state = target.build({'schema': 'attention-input/1', 'records': [{'anchor': c['id'], 'visibility': 'author_visible', 'text': c['text'], 'scores': []} for c in cases], 'a_reference': {'version': 'synthetic', 'items': []}})
        edits = []
        for case, record in zip(cases, state['records']):
            evidence = {'source_id': record['source_id'], 'section_id': case['id'], 'start': 0, 'end': len(case['text']), 'quote': case['text']}
            facets = [dict(f, facet_id=case['id'] + '-f' + str(i), evidence=[evidence], status='working') for i, f in enumerate(case['facets'])]
            edits.append({'opinion_id': case['id'] + '-op', 'record_id': record['record_id'], 'interpretation': '合成反例手工工作读法', 'status': 'working', 'facets': facets})
        target.apply({'schema': 'attention-patch/2', 'analysis_id': state['analysis_id'], 'base_revision': 0, 'actor': '合成编辑', 'reason': '保存必留方面和限定，不声称自动判读', 'edits': edits})
        target.close(); target = AttentionWorkspace(self.root / 'counterexamples'); self.addCleanup(target.close)
        saved = target.recover()
        self.assertEqual(len(saved['records']), 20)
        for case, op in zip(cases, saved['opinions']):
            with self.subTest(case=case['id']):
                self.assertEqual([f['interpretation'] for f in op['facets']], [f['interpretation'] for f in case['facets']])
                for actual, expected in zip(op['facets'], case['facets']):
                    for key, value in expected['qualifiers'].items():
                        self.assertEqual(actual['qualifiers'][key], value)
                    self.assertEqual(actual['kind'], expected['kind'])
        self.assertEqual(saved['opinions'][5]['facets'][2]['qualifiers']['conditions'], '无论能否补')
        self.assertEqual(saved['opinions'][14]['facets'][1]['kind'], 'disposition')

    def test_browser_clears_rich_fields_without_losing_other_facets_or_associations(self):
        import json
        import os
        from playwright.sync_api import sync_playwright
        from reviewproto.desktop import Controller
        qualifiers = ['object', 'direction', 'degree', 'negation', 'reasons', 'conditions', 'actions', 'examples', 'alternatives']
        cases = [('reported-clear', {'degree': '基本'}, {'function': '总体肯定', 'boilerplate_candidate': True}, 'content', False)]
        cases += [(key, {key: ['合成限定'] if key in {'reasons', 'conditions', 'actions', 'examples', 'alternatives'} else '合成限定'}, {'function': '', 'boilerplate_candidate': None}, 'content', False) for key in qualifiers]
        cases += [('function', {}, {'function': '总体肯定', 'boilerplate_candidate': None}, 'content', False),
                  ('candidate-true', {}, {'function': '', 'boilerplate_candidate': True}, 'content', False),
                  ('candidate-false', {}, {'function': '', 'boilerplate_candidate': False}, 'content', False),
                  ('kind', {}, {'function': '', 'boilerplate_candidate': None}, 'disposition', False),
                  ('compound', {'degree': '基本'}, {'function': '总体肯定', 'boilerplate_candidate': True}, 'content', True)]
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY', 'C:/Program Files/Google/Chrome/Application/chrome.exe'), headless=True)
            for name, initial_qualifiers, expression, kind, compound in cases:
                with self.subTest(case=name):
                    path = self.root / name
                    target = AttentionWorkspace(path)
                    self.addCleanup(target.close)
                    state = target.build({'schema': 'attention-input/1', 'records': [{'anchor': 'S1', 'visibility': 'visibility_unknown', 'text': self.state['records'][0]['text'], 'scores': []}], 'a_reference': {'version': 'synthetic-a', 'items': []}})
                    record = state['records'][0]
                    ev = {'source_id': record['source_id'], 'section_id': 'S1', 'start': 6, 'end': 11, 'quote': '基本清晰😀'}
                    first = {'facet_id': 'f-first', 'interpretation': '总体清晰', 'evidence': [ev], 'status': 'working', 'kind': kind, 'qualifiers': initial_qualifiers, 'expression': expression}
                    facets = [first]
                    themes, relations = [], []
                    if compound:
                        member = {'theme_id': 't', 'reason': '保留其他方面的原有归属', 'evidence': [ev], 'status': 'confirmed'}
                        first['themes'] = [copy.deepcopy(member)]
                        facets.append({'facet_id': 'f-other', 'interpretation': '另一内容范围', 'evidence': [ev], 'status': 'working', 'qualifiers': {'degree': '一定', 'conditions': ['仅在另一范围']}, 'expression': {'function': '另一功能', 'boilerplate_candidate': False}, 'themes': [member]})
                        themes = [{'theme_id': 't', 'label': '合成主题', 'definition': '两个范围分别保留', 'parent_ids': [], 'status': 'working'}]
                        relations = [{'relation_id': 'rel-other', 'type': 'scope', 'endpoints': [{'facet_id': 'f-other', 'role': '另一范围'}], 'direction': '无方向', 'scope': '仅另一范围', 'evidence': [ev], 'reading': '原关系保留', 'ambiguity': '', 'status': 'confirmed'}]
                    target.apply({'schema': 'attention-patch/2', 'analysis_id': state['analysis_id'], 'base_revision': 0, 'actor': '合成编辑', 'reason': '初始化已有富对象', 'edits': [{'opinion_id': 'op', 'record_id': record['record_id'], 'interpretation': '合成观点', 'status': 'working', 'facets': facets}], 'themes': themes, 'relations': relations})
                    before = target.state()
                    page = browser.new_page(accept_downloads=True, offline=True, viewport={'width': 1440, 'height': 1000})
                    page.on('dialog', lambda dialog: dialog.accept())
                    page.goto((path / 'attention.html').as_uri())
                    page.locator('#opinion').select_option('op')
                    page.locator('#facet').select_option('f-first')
                    for field in qualifiers:
                        page.locator('#' + field).fill('')
                    page.locator('#function').fill('')
                    page.locator('#boilerplate').select_option('unknown')
                    page.locator('#facet-kind').select_option('content')
                    page.locator('#actor').fill('合成浏览器编辑')
                    page.locator('#reason').fill('清除限定与表达判断')
                    page.locator('#stage').click()
                    with page.expect_download() as download:
                        page.locator('#download').focus(); page.keyboard.press('Enter')
                    patchfile = self.root / (name + '-clear.json')
                    download.value.save_as(patchfile)
                    patch = json.loads(patchfile.read_text(encoding='utf-8'))
                    self.assertEqual(patch['schema'], 'attention-patch/2')
                    controller = Controller(); controller.open_attention(path)
                    controller.apply_attention(patchfile); controller.recover_attention()
                    after = target.state()
                    saved = after['opinions'][0]['facets'][0]
                    self.assertEqual(after['revision'], 2)
                    self.assertEqual(saved['facet_id'], 'f-first')
                    self.assertTrue(all(saved['qualifiers'][key] == '' for key in qualifiers))
                    self.assertEqual(saved['expression'], {'function': '', 'boilerplate_candidate': None})
                    self.assertEqual(saved['kind'], 'content')
                    if compound:
                        self.assertEqual(after['opinions'][0]['facets'][1], before['opinions'][0]['facets'][1])
                        self.assertEqual(after['relations'], before['relations'])
                        self.assertEqual(saved['themes'][0]['theme_id'], 't')
                        self.assertEqual(saved['themes'][0]['status'], 'needs_review')
                    page.reload()
                    page.locator('#opinion').select_option('op')
                    page.locator('#facet').select_option('f-first')
                    for field in qualifiers + ['function']:
                        self.assertEqual(page.locator('#' + field).input_value(), '')
                    self.assertEqual(page.locator('#boilerplate').input_value(), 'unknown')
                    self.assertEqual(page.locator('#facet-kind').input_value(), 'content')
                    page.close()
            browser.close()

    def test_browser_multi_aspect_split_merge_theme_relation_download_apply_reopen(self):
        import json
        import os
        from playwright.sync_api import sync_playwright
        from reviewproto.desktop import Controller
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY', 'C:/Program Files/Google/Chrome/Application/chrome.exe'), headless=True)
            page = browser.new_page(accept_downloads=True, offline=True, viewport={'width': 1440, 'height': 1000})
            page.on('dialog', lambda d: d.accept())
            page.goto((self.root / 'analysis/attention.html').as_uri())
            errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
            page.locator('#passage').select_option('6:12')
            page.locator('#interpretation').fill('总体基本清晰')
            page.locator('#degree').fill('基本')
            page.locator('#function').fill('总体肯定')
            page.locator('#boilerplate').select_option('true')
            page.locator('#actor').fill('合成编辑'); page.locator('#reason').fill('保留不同判断与备用动作')
            page.locator('#stage').click()
            page.locator('#facet').select_option('')
            page.locator('#passage').select_option('12:20')
            page.locator('#interpretation').fill('证据并不充分')
            page.locator('#negation').fill('并不')
            page.locator('#stage').click()
            self.assertEqual(page.locator('#facet option').count(), 3)
            page.locator('#split').click()
            self.assertIn('关联待核', page.locator('#message').inner_text())
            options = page.locator('#merge-opinions option').all()
            page.locator('#merge-opinions').select_option([o.get_attribute('value') for o in options])
            page.locator('#merge').click()
            page.locator('#theme-label').fill('表达清晰程度')
            page.locator('#theme-definition').fill('表达组织及证据承载程度，保留判断差异')
            page.locator('#theme-stage').click()
            page.locator('#member-reason').fill('该方面直接评价表达')
            page.locator('#member-add').click()
            page.locator('#relation-type').fill('coexisting_readings')
            page.locator('#relation-role').fill('总体肯定')
            page.locator('#endpoint-add').click()
            page.locator('#facet').select_option(index=2)
            page.locator('#relation-role').fill('局部否定')
            page.locator('#endpoint-add').click()
            page.locator('#relation-direction').fill('并存，无因果方向')
            page.locator('#relation-scope').fill('总体表达与局部证据，不自动判矛盾')
            page.locator('#relation-reading').fill('相反方向在不同范围并存')
            page.locator('#relation-ambiguity').fill('不判定B专业结论')
            page.locator('#relation-stage').click()
            for width in (1440, 420):
                page.set_viewport_size({'width': width, 'height': 1000})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
            page.locator('#download').focus(); page.keyboard.press('Enter')
            # A second keyboard download is observed explicitly to save the file.
            with page.expect_download() as download:
                page.locator('#download').focus(); page.keyboard.press('Enter')
            patchfile = self.root / 'rich-draft.json'; download.value.save_as(patchfile)
            patch = json.loads(patchfile.read_text(encoding='utf-8'))
            self.assertEqual(patch['schema'], 'attention-patch/2')
            controller = Controller(); controller.open_attention(self.root / 'analysis')
            controller.apply_attention(patchfile); controller.recover_attention()
            page.reload()
            if not page.locator('#saved').is_visible():
                page.get_by_text('展开全部保存解释与撤回/替换历史（不随上方筛选）', exact=True).click()
            self.assertIn('总体基本清晰', page.locator('#saved').inner_text())
            if not page.locator('#saved').is_visible():
                page.get_by_text('展开全部保存解释与撤回/替换历史（不随上方筛选）', exact=True).click()
            self.assertIn('并不', page.locator('#saved').inner_text())
            if not page.locator('#saved-themes').is_visible():
                page.get_by_text('全部保存主题定义', exact=True).click()
            self.assertIn('表达清晰程度', page.locator('#saved-themes').inner_text())
            if not page.locator('#saved-relations').is_visible():
                page.get_by_text('全部保存关系与沿革（当前筛选的角色/范围见上方明细）', exact=True).click()
            self.assertIn('局部否定', page.locator('#saved-relations').inner_text())
            before = self.ws.state()
            page.locator('#actor').fill('合成编辑'); page.locator('#reason').fill('修正主题范围和关系范围')
            page.locator('#theme').select_option(index=1)
            page.locator('#theme-label').fill('表达与证据承载')
            page.locator('#theme-definition').fill('总体表达与局部证据的承载范围')
            page.locator('#theme-stage').click()
            page.locator('#relation').select_option(index=1)
            page.locator('#relation-scope').fill('仅总体表达与局部证据，修正工作范围')
            page.locator('#relation-stage').click()
            with page.expect_download() as download:
                page.locator('#download').focus(); page.keyboard.press('Enter')
            download.value.save_as(patchfile)
            controller.apply_attention(patchfile); controller.recover_attention(); page.reload()
            after = self.ws.state()
            self.assertEqual(after['themes'][0]['theme_id'], before['themes'][0]['theme_id'])
            self.assertEqual(after['relations'][0]['relation_id'], before['relations'][0]['relation_id'])
            if not page.locator('#saved-relations').is_visible():
                page.get_by_text('全部保存关系与沿革（当前筛选的角色/范围见上方明细）', exact=True).click()
            self.assertIn('修正工作范围', page.locator('#saved-relations').inner_text())
            evidence_dir = Path(os.environ.get('ATTENTION_T2_EVIDENCE_DIR', self.root / 'screens'))
            evidence_dir.mkdir(parents=True, exist_ok=True)
            for width in (1440, 420):
                page.set_viewport_size({'width': width, 'height': 1000})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                page.screenshot(path=str(evidence_dir / ('rich-saved-' + str(width) + '.png')), full_page=True)
                page.locator('#saved-relations').scroll_into_view_if_needed()
                page.screenshot(path=str(evidence_dir / ('relation-detail-' + str(width) + '.png')))
            self.assertEqual(errors, [])
            browser.close()
