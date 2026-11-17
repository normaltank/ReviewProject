"""Connector admission only; accepted relations still require semantic review."""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_candidates import generate, accept, ReplayProvider


class RelationConnectors(unittest.TestCase):
    def run_relation(self, original, kind, *, evidence=None, endpoint='left', roundtrip=False):
        left,right=original.split('，',1)
        with tempfile.TemporaryDirectory() as tmp, closing(AttentionWorkspace(Path(tmp)/'pack')) as ws:
            ws.build({'schema':'attention-input/1','records':[{'anchor':'s','visibility':'author_visible','text':original}],
                      'a_reference':{'version':'none','items':[]}})
            def quote(text): return {'section':'s1','quote':text}
            b={'opinions':[{'summary':'两种安排','facets':[
                {'ref':'left','focus':'第一项安排','state':'建议','boilerplate':False,'evidence':[quote(left)],'qualifiers':{},'themes':[]},
                {'ref':'right','focus':'另一项安排','state':'建议','boilerplate':False,'evidence':[quote(right)],'qualifiers':{},'themes':[]}]}],
                'relations':[{'type':kind,'endpoints':[{'facet':endpoint,'role':'第一项'},{'facet':'right','role':'第二项'}],
                    'direction':'两项安排的联系','scope':'两项安排','reading':'仅记录原文明示的安排联系','ambiguity':'',
                    'evidence':[quote(original if evidence is None else evidence)]}],'unprocessed':[]}
            run=generate(ws,'connector',ReplayProvider([b]))
            if not roundtrip:
                return run
            accept(ws,'connector',actor='合成编辑',reason='核对明示对照')
            with closing(AttentionWorkspace(ws.path)) as reopened:
                return run,reopened.state()

    def test_er_bu_shi_contrast_survives_accept_and_reopen_with_evidence(self):
        original='请交代删节的规则，而不是增加访谈人数。'
        run,saved=self.run_relation(original,'对照/排除',roundtrip=True)
        self.assertEqual(len(run['patch']['relations']),1,run['rejected'])
        self.assertEqual(run['rejected'],[])
        relation=saved['relations'][0]
        self.assertEqual(relation['type'],'对照/排除')
        self.assertEqual(relation['status'],'needs_review')
        self.assertEqual(relation['evidence'][0]['quote'],original)
        self.assertEqual(len(relation['endpoints']),2)
        self.assertEqual([e['role'] for e in relation['endpoints']],['第一项','第二项'])
        unsupported=self.run_relation(original,'理由支持')
        self.assertEqual(unsupported['patch']['relations'],[])
        self.assertIn('E_ATTENTION_RELATION_CONNECTION',str(unsupported['rejected']))
        missing=self.run_relation('请交代删节规则，先保留现有节录。可以补说明，而不是增加访谈人数。',
            '对照/排除',evidence='而不是增加访谈人数。')
        self.assertEqual(missing['patch']['relations'],[])
        self.assertIn('E_ATTENTION_RELATION_RANGE',str(missing['rejected']))

    def test_alternative_forms_are_admitted_in_alternative_branch(self):
        for original in ('可以使用纸质目录，使用电子目录也行。',
                         '先给出两个方案，现场登记和预约登记二选一。',
                         '提交有两种路径，在线办理和柜台办理选一种。',
                         '这里列出两项办法，打印与抄录择一。'):
            with self.subTest(original=original):
                run=self.run_relation(original,'备选')
                self.assertEqual(len(run['patch']['relations']),1,run['rejected'])
                self.assertEqual(run['patch']['relations'][0]['status'],'needs_review')

    def test_buguo_contrast_is_admitted_without_turning_it_into_causality(self):
        original='术语表已经清楚，不过索引位置仍需说明。'
        run=self.run_relation(original,'转折')
        self.assertEqual(len(run['patch']['relations']),1,run['rejected'])
        run=self.run_relation(original,'理由支持')
        self.assertEqual(run['patch']['relations'],[])
        self.assertIn('E_ATTENTION_RELATION_CONNECTION',str(run['rejected']))

    def test_choice_does_not_become_simultaneous_or_allow_unsupported_types(self):
        original='提交有两种路径，线上办理和柜台办理二选一。'
        for kind in ('动作组','理由支持','自动合并'):
            with self.subTest(kind=kind):
                run=self.run_relation(original,kind)
                self.assertEqual(run['patch']['relations'],[])
                self.assertIn('E_ATTENTION_RELATION_CONNECTION',str(run['rejected']))
        run=self.run_relation('可以使用纸质目录，电子目录也许稍后提供。','备选')
        self.assertEqual(run['patch']['relations'],[])
        self.assertIn('E_ATTENTION_RELATION_CONNECTION',str(run['rejected']))

    def test_connector_cannot_repair_missing_endpoint_evidence(self):
        original='可以使用纸质目录，便于现场查询。使用电子目录也行。'
        run=self.run_relation(original,'备选',evidence='使用电子目录也行。')
        self.assertEqual(run['patch']['relations'],[])
        self.assertIn('E_ATTENTION_RELATION_RANGE',str(run['rejected']))

    def test_conditional_role_and_time_clause_guards_remain(self):
        run=self.run_relation('若版面不足，改用编号索引也行。','条件约束')
        self.assertEqual(run['patch']['relations'],[])
        self.assertIn('E_ATTENTION_RELATION_ROLE',str(run['rejected']))
        run=self.run_relation('资料齐备时才归档，另附索引。','条件约束')
        self.assertEqual(run['patch']['relations'],[])
        self.assertIn('E_ATTENTION_RELATION_CONNECTION',str(run['rejected']))
