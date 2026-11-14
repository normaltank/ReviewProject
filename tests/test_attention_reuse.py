"""Ordinary Tk entry -> ordinary Chrome forms -> download/apply/reopen.

Only the OS directory chooser is mocked. All material is synthetic.
"""
import hashlib
import json
import os
import tempfile
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from reviewproto.attention import AttentionWorkspace
from reviewproto.attention_input_ui import AttentionInputWindow
from reviewproto.desktop import Controller
from reviewproto.core import ReviewError

S1 = [('湖面-α', '练习甲', '😀对象说明清楚。对象说明清楚。\n保留 <b>字面标记</b> 与第二处重复句。', [('自由原分标签', ' 7 / 9 ')]),
      ('山谷-β', '练习甲', '方法说明尚可；适用范围暂未明确。', [])]
S2 = [('研究-甲', '练习乙', '研究对象写清了，但结论需说明条件。\n如果不能补充材料，可以缩小主张。', [('表达', ' 4.0 '), ('方法', '未填')]),
      ('时段-乙', '练习乙', '资料时段应注明；已有界限可以保留。', []),
      ('版式-丙', '练习丙', '排版清楚。', [('版式', '可'), ('其他', '—'), ('自定义', ' 0 ')])]


class AttentionReuse(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = tk.Tk(); self.root.withdraw(); self.addCleanup(self.root.destroy)
        self.controller = Controller()
        self.window = AttentionInputWindow(self.root, self.controller)
        self.evidence = Path(os.environ['ATTENTION_REUSE_EVIDENCE_DIR']) if os.environ.get('ATTENTION_REUSE_EVIDENCE_DIR') else None
        if self.evidence: self.evidence.mkdir(parents=True, exist_ok=True)
        self.errors, self.http = [], []
        self.report = {}

    def state(self, path=None):
        with closing(AttentionWorkspace(path or self.controller.attention_path)) as ws:
            return ws.state()

    def enter_b(self, row):
        anchor, group, text, scores = row
        w = self.window
        w.anchor.set(anchor); w.locator.set('合成定位：' + anchor); w.paper.set(group)
        w.quote.insert('1.0', text)
        for label, value in scores:
            w.score_label.set(label); w.score_value.set(value); w.add_score_button.invoke()
        w.save_b_button.invoke()

    def enter_a(self, w, version, parts, items):
        w.version.set(version)
        for label in parts:
            w.part_label.set(label); w.save_part_button.invoke()
        for part, text, locator in items:
            w.part_box.current(part); w.item_locator.set(locator); w.a_text.insert('1.0', text); w.save_a_button.invoke()

    def build(self):
        with patch('tkinter.filedialog.askdirectory', return_value=str(self.folder)):
            self.window.build_button.invoke()
        self.assertIsNotNone(self.controller.attention_path, self.window.status.get())
        return self.controller.attention_path

    def tk_shot(self, w, name, tab):
        if not self.evidence: return
        from PIL import ImageGrab
        w.tabs.select(tab)
        w.preview.yview_moveto(0)
        for width, height in [(980, 780), (760, 640)]:
            w.window.geometry(f'{width}x{height}+40+40'); w.window.attributes('-topmost', True); w.window.lift(); self.root.update()
            time.sleep(0.2); self.root.update()
            x, y = w.window.winfo_rootx(), w.window.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(self.evidence / f'{name}-{width}.png')
        w.window.attributes('-topmost', False)

    def page(self, browser):
        page = browser.new_page(offline=True, accept_downloads=True, viewport={'width':1440, 'height':1000})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('request', lambda r: self.http.append(r.url) if r.url.startswith(('https:', 'http:')) else None)
        page.on('dialog', lambda d: d.accept())
        page.goto((self.controller.attention_path / 'attention.html').as_uri())
        return page

    def audit(self, page, reason='按给定原话保存工作解释'):
        page.locator('#actor').fill('合成核对者'); page.locator('#reason').fill(reason)

    def opinion(self, page, interpretation, passage=1):
        page.locator('#opinion').select_option('')
        page.locator('#passage').select_option(index=passage)
        page.locator('#interpretation').fill(interpretation); page.locator('#stage').click()
        self.assertNotEqual(page.locator('#opinion').input_value(), '', page.locator('#message').inner_text())
        return page.locator('#opinion').input_value(), page.locator('#facet').input_value()

    def theme(self, page, label):
        page.locator('#theme-label').fill(label); page.locator('#theme-definition').fill('保留给定内容范围，不判断专业正确性')
        page.locator('#theme-stage').click()
        page.locator('#member-reason').fill('所选原话直接表达此方面'); page.locator('#member-add').click()

    def save(self, page, name):
        before = self.state()
        self.assertTrue(page.locator('#download').is_enabled(), page.locator('#message').inner_text() + page.locator('#draft').inner_text())
        with page.expect_download() as download: page.locator('#download').click()
        file = self.folder / (name + '.json'); download.value.save_as(file)
        self.assertEqual(self.state(), before, 'Download must not change saved state')
        self.assertIn('已保存修订 ' + str(before['revision']), page.get_by_role('region', name='当前关注概览').inner_text())
        self.controller.apply_attention(file); self.controller.recover_attention(); page.reload()
        after = self.state()
        self.assertEqual(after['revision'], before['revision'] + 1)
        if self.evidence: (self.evidence / (name + '-patch.json')).write_bytes(file.read_bytes())
        return after, file

    def web_shots(self, page, name):
        for width in (1440, 420):
            page.set_viewport_size({'width':width, 'height':1000})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
            if self.evidence:
                page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(self.evidence / f'{name}-full-{width}.png'), full_page=True)
                page.get_by_role('region', name='当前关注概览').screenshot(path=str(self.evidence / f'{name}-overview-{width}.png'))
        page.set_viewport_size({'width':1440, 'height':1000})

    def finish(self, name):
        self.assertEqual(self.errors, []); self.assertEqual(self.http, [])
        self.report.update(pageerrors=self.errors, external_http=self.http)
        if self.evidence: (self.evidence / (name + '-results.json')).write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_s1_second_duplicate_and_theme_saved_only_after_apply(self):
        for row in S1: self.enter_b(row)
        self.window.b_list.selection_set(0); self.window.load_b(); self.root.update()
        self.tk_shot(self.window, 's1-b', self.window.b_tab)
        self.window.save_b_button.invoke()
        self.tk_shot(self.window, 's1-checklist', self.window.review_tab)
        path = self.build(); initial = self.state()
        self.assertEqual([r['text'] for r in initial['records']], [r[2] for r in S1])
        self.assertEqual(initial['records'][0]['scores'], [{'label':'自由原分标签', 'raw_value':' 7 / 9 '}])
        self.assertEqual(initial['a_reference']['items'], [])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            try:
                page = self.page(browser); self.audit(page)
                self.assertEqual(page.locator('#source b').count(), 0)
                self.opinion(page, '第二处对象说明的肯定', 2); self.theme(page, '对象界定')
                saved, draft = self.save(page, 's1')
                ev = saved['opinions'][0]['facets'][0]['evidence'][0]
                self.assertEqual((ev['start'], ev['end'], ev['quote']), (8, 15, '对象说明清楚。'))
                self.assertEqual(len(saved['opinions']), 1)
                self.assertIn('1/2', page.get_by_role('region', name='当前关注概览').inner_text())
                for detail in page.locator('#view-detail > details[id^="view-record-"]').all(): detail.locator('summary').first.click()
                for row in S1: self.assertIn(row[2], page.locator('#view-detail').text_content())
                self.assertFalse(page.locator('#view-graph-toggle').is_checked())
                self.web_shots(page, 's1-saved')
                # Prepare a new ordinary correction before source becomes stale.
                self.audit(page, '绑定失效拒收新的未应用纠正')
                page.locator('#opinion').select_option(index=1)
                page.locator('#interpretation').fill('待保存的合成纠正'); page.locator('#stage').click()
                with page.expect_download() as d: page.locator('#download').click()
                draft = self.folder / 'pending-correction.json'; d.value.save_as(draft)
                # Exact-byte B binding loss/recovery on this independent synthetic package.
                source = path / 'inputs/b-input.json'; original = source.read_bytes()
                source.write_bytes(original + b' ')
                self.controller.recover_attention(); page.reload()
                self.assertIn('来源失效', page.get_by_role('region', name='当前关注概览').inner_text())
                self.assertIn(S1[0][2], page.locator('#source').text_content())
                before = self.state()
                with self.assertRaisesRegex(ReviewError, 'E_ATTENTION_REVALIDATION'): self.controller.apply_attention(draft)
                self.assertEqual(self.state()['revision'], before['revision'])
                self.web_shots(page, 's1-stale')
                source.write_bytes(original); self.controller.recover_attention(); page.reload()
                self.assertEqual(self.state()['material_status'], 'current')
                source.rename(source.with_suffix('.missing'))
                self.controller.recover_attention(); self.assertEqual(self.state()['b_material_status'], 'needs_revalidation')
                source.with_suffix('.missing').rename(source); self.controller.recover_attention()
                self.assertEqual(self.state()['material_status'], 'current')
                self.report.update(analysis_id=saved['analysis_id'], evidence=ev, N=2, scores=1, restored=True)
            finally: browser.close()
        self.finish('s1')

    def test_s2_a_replacement_changed_b_and_shared_saved_views(self):
        # Keep a fully annotated S1 package while working on S2 in the same controller.
        for row in S1: self.enter_b(row)
        s1_path = self.build()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            try:
                page = self.page(browser); self.audit(page)
                self.opinion(page, '对象说明的工作解释', 2); self.theme(page, '对象界定')
                self.save(page, 's1-protected'); page.close()
            finally: browser.close()
        s1_hashes = {str(f.relative_to(s1_path)):hashlib.sha256(f.read_bytes()).hexdigest() for f in s1_path.rglob('*') if f.is_file()}
        self.window.window.destroy(); self.window = AttentionInputWindow(self.root, self.controller)
        for row in S2: self.enter_b(row)
        self.enter_a(self.window, 'focus-β-01', ['表达组织','时间','空分组'], [
            (0,'说明研究对象及其边界。','合成A-首段1'), (0,'区分证据与结论的适用条件。','合成A-首段2'),
            (1,'适用时说明资料时段，不预设统一年限。','合成A-次段1')])
        self.tk_shot(self.window, 's2-checklist', self.window.review_tab)
        path = self.build(); initial = self.state()
        self.assertEqual([r['text'] for r in initial['records']], [r[2] for r in S2])
        self.assertEqual([r['scores'] for r in initial['records']], [[{'label':label,'raw_value':value} for label,value in row[3]] for row in S2])
        self.assertEqual([p['label'] for p in initial['a_reference']['parts']], ['表达组织','时间','空分组'])
        self.assertEqual([(a['text'],a['locator']) for a in initial['a_reference']['items']], [('说明研究对象及其边界。','合成A-首段1'),('区分证据与结论的适用条件。','合成A-首段2'),('适用时说明资料时段，不预设统一年限。','合成A-次段1')])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['REVIEW_BROWSER_BINARY'], headless=True)
            try:
                page = self.page(browser); self.audit(page)
                first_op, first_f = self.opinion(page, '研究对象明确，结论需说明条件')
                self.theme(page, '条件说明')
                page.locator('#a-item').select_option(initial['a_reference']['items'][0]['id']); page.locator('#a-scope').fill('研究对象')
                page.locator('#a-reason').fill('对象表述对应首条关注'); page.locator('#a-save').click()
                self.assertIn('关联已加入未应用草稿', page.locator('#message').inner_text())
                second_op, second_f = self.opinion(page, '不能补材料时可缩小主张', 2)
                page.locator('#conditions').fill('如果不能补充材料'); page.locator('#actions').fill('可以缩小主张')
                page.locator('#stage').click()
                page.locator('#member-reason').fill('条件限定主张范围'); page.locator('#member-add').click()
                for fid, role in [(first_f,'受限定结论'),(second_f,'条件与备用动作')]:
                    page.locator('#relation-facet').select_option(fid); page.locator('#relation-role').fill(role); page.locator('#endpoint-add').click()
                for key, value in [('type','条件限制'),('direction','条件限定主张'),('scope','仅第一条的结论与补充材料条件'),('reading','不能补充时可以缩小，不推反向保证')]: page.locator('#relation-'+key).fill(value)
                page.locator('#relation-stage').click()
                saved, _ = self.save(page, 's2')
                self.assertEqual(len(saved['opinions']),2); self.assertEqual(len(saved['relations']),1)
                self.assertEqual(saved['opinions'][1]['facets'][0]['qualifiers']['conditions'],'如果不能补充材料')
                overview = page.get_by_role('region', name='当前关注概览')
                self.assertIn('1/3', overview.inner_text()); self.assertIn('2 个观点 / 2 个方面', overview.inner_text())
                page.locator('#view-matrix-toggle').check(); page.locator('#view-graph-toggle').check()
                self.assertEqual(page.locator('#view-matrix tbody tr').count(),3)
                self.assertIn('条件限制',page.locator('#view-graph').text_content())
                self.assertIn('空分组',page.locator('#view-summary').text_content())
                self.assertIn('0/3',page.locator('#view-summary').text_content())
                page.locator('#view-paper').select_option(json.dumps('练习乙',ensure_ascii=False))
                self.assertEqual(page.locator('#view-detail > details[id^="view-record-"]').count(),2)
                self.assertEqual(page.locator('#view-matrix tbody tr').count(),2)
                self.assertIn('1/2',overview.inner_text()); self.assertIn('条件限制',page.locator('#view-graph').text_content())
                page.locator('#view-paper').select_option(json.dumps('练习丙',ensure_ascii=False))
                self.assertEqual(page.locator('#view-detail > details[id^="view-record-"]').count(),1)
                self.assertIn('0/1',overview.inner_text()); self.assertNotIn('条件限制',page.locator('#view-graph').text_content())
                page.get_by_role('button',name='清除筛选').click()
                page.locator('#view-graph-record').select_option(initial['records'][0]['record_id'])
                for detail in page.locator('#view-detail > details').all(): detail.locator('summary').first.click()
                self.web_shots(page,'s2-saved')
                # Native A-only entry preserves B/opinion identities, then ordinary mapping correction.
                a = AttentionInputWindow(self.root,self.controller,a_only=True)
                self.enter_a(a,'focus-β-02',['对象与条件','保留空组'],[(0,'可以说明对象边界。','换版-1'),(0,'必要时限定结论条件。','换版-2')])
                a.actor.set('合成核对者'); a.reason.set('显式更新A内容及结构')
                self.tk_shot(a,'s2-a-only',a.review_tab); a.import_a_button.invoke()
                changed = self.state(); self.assertEqual(changed['records'],saved['records'])
                self.assertEqual(changed['analysis_id'],saved['analysis_id'])
                self.assertEqual([o['opinion_id'] for o in changed['opinions']],[first_op,second_op])
                link = changed['opinions'][0]['facets'][0]['a_links'][0]
                self.assertEqual(link['status'],'needs_review'); self.assertEqual(link['version'],'focus-β-01')
                self.assertIn('focus-β-01',[h['a_reference']['version'] for h in changed['a_reference_history']])
                page.reload(); self.audit(page,'明确纠正新A映射')
                page.locator('#opinion').select_option(first_op); page.locator('#a-link').select_option(index=1)
                page.locator('#a-item').select_option(changed['a_reference']['items'][0]['id']); page.locator('#a-status').select_option('working')
                page.locator('#a-scope').fill('改写后对象边界'); page.locator('#a-reason').fill('逐字核对新条目后重新对应'); page.locator('#a-save').click()
                corrected,_ = self.save(page,'s2-corrected'); self.assertEqual(corrected['opinions'][0]['facets'][0]['a_links'][-1]['version'],'focus-β-02')
                self.web_shots(page,'s2-corrected')
                if self.evidence:
                    page.locator('#opinion').select_option(first_op); page.locator('#a-link').select_option(index=1)
                    for width in (1440,420):
                        page.set_viewport_size({'width':width,'height':1000})
                        page.locator('#a-scope').scroll_into_view_if_needed()
                        page.screenshot(path=str(self.evidence / f's2-correction-controls-{width}.png'))
                # Changed B: same checklist, edit first, delete second, add another; do not reopen old DB after baseline.
                page.close()
                old_files = {str(f.relative_to(path)):hashlib.sha256(f.read_bytes()).hexdigest() for f in path.rglob('*') if f.is_file()}
                w=self.window; w.b_list.selection_set(0); w.load_b(); w.quote.delete('1.0','end'); w.quote.insert('1.0','研究对象已更正；主张仍需条件。'); w.save_b_button.invoke()
                w.b_list.selection_clear(0,'end'); w.b_list.selection_set(1); w.remove_b_button.invoke()
                self.enter_b(('新增检查-丁','练习丁','补充说明数据来源。',[]))
                newer=self.build(); new=self.state()
                self.assertNotEqual(newer,path); self.assertNotEqual(new['analysis_id'],corrected['analysis_id'])
                self.assertEqual(new['opinions'],[]); self.assertEqual(len(new['records']),3)
                self.assertEqual(sum(len(r['scores']) for r in new['records']),5)
                self.assertNotIn('时段-乙',[r['anchor'] for r in new['records']])
                self.assertEqual(new['records'][0]['text'],'研究对象已更正；主张仍需条件。')
                self.assertEqual({str(f.relative_to(path)):hashlib.sha256(f.read_bytes()).hexdigest() for f in path.rglob('*') if f.is_file()},old_files)
                a.import_a_button.invoke(); self.assertIn('E_ATTENTION_TARGET',a.status.get()); self.tk_shot(a,'s2-a-target-error',a.review_tab)
                self.assertEqual({str(f.relative_to(s1_path)):hashlib.sha256(f.read_bytes()).hexdigest() for f in s1_path.rglob('*') if f.is_file()}, s1_hashes)
                self.report.update(s1_unchanged=True, analysis_id=corrected['analysis_id'], changed_b_analysis=new['analysis_id'], N=3, scores=5, old_package_hashes=old_files, old_package_unchanged=True, new_opinions=0)
            finally: browser.close()
        self.finish('s2')


