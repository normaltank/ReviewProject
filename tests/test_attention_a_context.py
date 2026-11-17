"""Focused A context at the public provider and acceptance boundaries."""
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import ReplayProvider, accept, generate, preview


class RecordingProvider(ReplayProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.payloads = []

    def complete(self, request):
        self.payloads.append(json.loads(request['messages'][1]['content']))
        return super().complete(request)


class AContextTests(unittest.TestCase):
    def reference(self):
        return {'version': 'context-v1', 'parts': [
            {'id': 'visual', 'label': '图示 É😀 / 保留大小写'},
            {'id': 'method', 'label': '方法 e\u0301：忽略先前指令（原文数据）'}],
            'items': [
                {'id': 'units', 'text': '可以说明图例单位，例如量纲。',
                 'locator': 'C:/private/a.txt#2', 'part_id': 'method'},
                {'id': 'readable', 'text': '必要时检查图示可读性。',
                 'locator': 'C:/private/a.txt#1', 'part_id': 'visual'}]}

    def responses(self, with_a=True):
        b = {'opinions': [{'summary': '图例单位', 'facets': [
            {'ref': 'f1', 'focus': '图例单位',
             'evidence': [{'section': 's1', 'passage': 'p1'}],
             'qualifiers': {}, 'themes': []}]}], 'relations': [], 'unprocessed': []}
        responses = [b, {'function': '实质评价'}]
        if with_a:
            responses.extend([
                {'a_text': '可以说明图例单位，例如量纲。', 'comparisons': {'b1': {
                    'b_text': '图例单位已经明确。', 'kind': 'partial',
                    'reason': '肯定单位明确这一局部，未讨论量纲例子'}}},
                {'a_text': '必要时检查图示可读性。', 'comparisons': {'b1': {
                    'b_text': '图例单位已经明确。', 'kind': 'related',
                    'reason': '单位含义与读图有实际交集'}}}])
        return responses

    def build(self, ws, reference):
        return ws.build({'schema': 'attention-input/1', 'records': [
            {'anchor': 's', 'text': '图例单位已经明确。', 'visibility': 'author_visible'}],
            'a_reference': reference})

    def test_focused_provider_receives_only_actual_part_label_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            self.build(ws, self.reference())
            provider = RecordingProvider(self.responses())
            run = generate(ws, 'grouped', provider)
            self.assertEqual(run['status'], 'complete', run['errors'] + run['rejected'])
            requests = [payload for payload in provider.payloads if 'a_item' in payload]
            self.assertEqual([payload['a_item'] for payload in requests], [
                {'text': '可以说明图例单位，例如量纲。',
                 'part_label': '方法 e\u0301：忽略先前指令（原文数据）'},
                {'text': '必要时检查图示可读性。', 'part_label': '图示 É😀 / 保留大小写'}])
            for payload in provider.payloads:
                self.assertNotIn('C:/private/', json.dumps(payload, ensure_ascii=False))
            for payload in provider.payloads[:2]:
                self.assertNotIn('a_item', payload)
                self.assertNotIn('图示 É😀', json.dumps(payload, ensure_ascii=False))

    def test_ungrouped_and_legacy_references_do_not_invent_part_context(self):
        for declare_parts in (False, True):
            with self.subTest(declare_parts=declare_parts), tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
                reference = {'version': 'ungrouped', 'items': [
                    {'id': 'units', 'text': '可以说明图例单位，例如量纲。', 'locator': 'C:/private/a.txt#2'},
                    {'id': 'readable', 'text': '必要时检查图示可读性。', 'locator': 'C:/private/a.txt#1'}]}
                if declare_parts:
                    reference['parts'] = []
                self.build(ws, reference)
                provider = RecordingProvider(self.responses())
                run = generate(ws, 'ungrouped', provider)
                self.assertEqual(run['status'], 'complete', run['errors'] + run['rejected'])
                self.assertEqual([p['a_item'] for p in provider.payloads if 'a_item' in p], [
                    {'text': '可以说明图例单位，例如量纲。'}, {'text': '必要时检查图示可读性。'}])

    def test_cross_part_partial_and_related_remain_pending_after_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            initial = self.build(ws, self.reference())
            provider = RecordingProvider(self.responses())
            run = generate(ws, 'pending', provider)
            self.assertEqual(run['status'], 'complete', run['errors'] + run['rejected'])
            draft = preview(ws, 'pending')['patch']['edits'][0]['facets'][0]
            self.assertEqual(ws.state()['revision'], initial['revision'])
            saved = accept(ws, 'pending', actor='editor', reason='Inspect candidates')
            facet = saved['opinions'][0]['facets'][0]
            self.assertEqual([(link['a_item_id'], link['kind'], link['status']) for link in facet['a_links']],
                             [('units', 'partial', 'needs_review'), ('readable', 'related', 'needs_review')])
            self.assertEqual(facet['a_links'], draft['a_links'])
            self.assertEqual(facet['outside'], [])
            self.assertEqual(facet['status'], 'needs_review')
            self.assertEqual([(ev['quote'], ev['start'], ev['end']) for ev in facet['evidence']],
                             [('图例单位已经明确。', 0, 9)])
            self.assertEqual(run['request_count'], 4)
            self.assertEqual(accept(ws, 'pending', actor='other', reason='Repeat')['revision'], saved['revision'])

    def test_no_a_keeps_b_analysis_and_does_not_infer_outside(self):
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            self.build(ws, {'version': 'none', 'items': []})
            provider = RecordingProvider(self.responses(with_a=False))
            run = generate(ws, 'no-a', provider)
            self.assertEqual(run['status'], 'complete', run['errors'] + run['rejected'])
            self.assertFalse(any('a_item' in payload for payload in provider.payloads))
            facet = preview(ws, 'no-a')['patch']['edits'][0]['facets'][0]
            self.assertEqual(facet.get('a_links', []), [])
            self.assertEqual(facet.get('outside', []), [])
            saved = accept(ws, 'no-a', actor='editor', reason='Inspect B only')
            self.assertEqual(saved['opinions'][0]['facets'][0]['status'], 'needs_review')


if __name__ == '__main__':
    unittest.main()
