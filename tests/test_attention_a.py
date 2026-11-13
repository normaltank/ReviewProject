import copy
import tempfile
import unittest
from pathlib import Path
from reviewproto.attention import AttentionWorkspace

class AttentionA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = AttentionWorkspace(self.root/'analysis'); self.addCleanup(self.ws.close)
        self.state = self.ws.build({'schema':'attention-input/1','records':[{'anchor':'S','visibility':'author_visible','text':'可以说明样本与结果，但总体认可不代表全部覆盖。','scores':[]}], 'a_reference':{'version':'v1','parts':[{'id':'p','label':'合成部分'}],'items':[{'id':'a','text':'可以说明样本','locator':'synthetic:1','part_id':'p'}]}})
    def patch(self, **kw):
        return dict(schema='attention-patch/2',analysis_id=self.state['analysis_id'],base_revision=self.ws.state()['revision'],actor='合成编辑',reason='核对范围',**kw)
    def ev(self):
        r=self.state['records'][0]
        return dict(source_id=r['source_id'],section_id='S',start=0,end=7,quote=r['text'][:7])
    def op(self):
        return dict(opinion_id='o',record_id=self.state['records'][0]['record_id'],interpretation='两个范围',status='working',facets=[dict(facet_id='f',interpretation='样本说明',status='working',evidence=[self.ev()],a_links=[dict(a_item_id='a',version='v1',kind='partial',scope='样本',reason='仅样本说明',evidence=[self.ev()],status='working')],outside=[dict(scope='总体认可',reason='未指定清单内容',evidence=[self.ev()],status='working')])])
    def test_multiple_a_and_outside_survive_apply_and_reopen_then_clear(self):
        op=self.op(); op['facets'][0]['a_links'].append(dict(op['facets'][0]['a_links'][0],kind='undetermined',a_item_id=None,scope='结果范围',reason='尚不能确定条目'))
        self.ws.apply(self.patch(edits=[op]))
        self.ws.close(); self.ws=AttentionWorkspace(self.root/'analysis'); self.addCleanup(self.ws.close)
        saved=self.ws.recover(); f=saved['opinions'][0]['facets'][0]
        self.assertEqual([l['kind'] for l in f['a_links']], ['partial','undetermined'])
        self.assertEqual(f['outside'][0]['scope'],'总体认可')
        op=copy.deepcopy(saved['opinions'][0]); op={k:v for k,v in op.items() if k in {'opinion_id','record_id','interpretation','status','facets','replaces'}}
        op['facets'][0]['a_links']=[]; op['facets'][0]['outside']=[]
        self.ws.apply(self.patch(edits=[op]))
        self.assertEqual(self.ws.recover()['opinions'][0]['facets'][0]['a_links'],[])
        self.assertEqual(self.ws.recover()['opinions'][0]['facets'][0]['outside'],[])
    def test_explicit_import_keeps_identity_history_and_does_not_bypass_b_source(self):
        import json
        from reviewproto.core import ReviewError
        source=self.root/'a.json'
        def write(version):
            source.write_text(json.dumps({'schema':'attention-a-input/1','a_reference':{'version':version,'parts':[{'id':'p','label':'新部分'}],'items':[{'id':'b','text':'必要时说明结果','locator':'synthetic:2','part_id':'p'}]}}),encoding='utf-8')
        self.ws.apply(self.patch(edits=[self.op()]))
        identity=self.ws.state()['opinions'][0]['facets'][0]['facet_id']
        write('v2'); self.ws.import_a(source,actor='编辑',reason='显式接续')
        write('v3')
        self.assertEqual(self.ws.recover()['a_material_status'],'needs_revalidation')
        self.assertEqual(self.ws.state()['opinions'][0]['facets'][0]['a_links'][0]['status'],'needs_review')
        self.ws.import_a(source,actor='编辑',reason='旧A已变化后明确换版')
        saved=self.ws.recover()
        self.assertEqual(saved['material_status'],'current')
        self.assertEqual(saved['analysis_id'],self.state['analysis_id'])
        self.assertEqual(saved['opinions'][0]['facets'][0]['facet_id'],identity)
        self.assertEqual([h['a_reference']['version'] for h in saved['a_reference_history']],['v1','v2'])
        self.assertEqual(saved['opinions'][0]['facets'][0]['a_links'][0]['version'],'v1')
        self.assertEqual(len(saved['history']),3)
        draft=self.root/'b.json'; draft.write_text(json.dumps({'schema':'attention-input/1','records':[{'anchor':'S','text':'合成','visibility':'author_visible'}],'a_reference':{'version':'old','items':[]}}),encoding='utf-8')
        target=AttentionWorkspace(self.root/'bound'); self.addCleanup(target.close);target.build(input_path=draft)
        draft.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_REVALIDATION'):target.import_a(source,actor='编辑',reason='不得绕过B')
        self.assertEqual(target.state()['revision'],0)

    def test_invalid_a_version_item_and_evidence_reject_whole_transaction(self):
        from reviewproto.core import ReviewError
        for field,value in [('version','wrong'),('a_item_id','unknown'),('kind','invented')]:
            op=self.op(); op['facets'][0]['a_links'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ReviewError):self.ws.apply(self.patch(edits=[op]))
            self.assertEqual(self.ws.state()['revision'],0)
        op=self.op();op['facets'][0]['a_links'][0]['evidence'][0]['quote']='错误引文'
        with self.assertRaises(ReviewError):self.ws.apply(self.patch(edits=[op]))
        self.assertEqual(self.ws.state()['opinions'],[])

    def test_chrome_ordinary_a_controls_download_apply_reopen_and_clear(self):
        import json,os
        from playwright.sync_api import sync_playwright
        from reviewproto.desktop import Controller
        op=self.op();op['facets']=[dict(op['facets'][0],a_links=[],outside=[]),dict(op['facets'][0],facet_id='other',interpretation='其他范围保留')]
        self.ws.apply(self.patch(edits=[op]))
        untouched=copy.deepcopy(self.ws.state()['opinions'][0]['facets'][1])
        controller=Controller();controller.open_attention(self.root/'analysis')
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('REVIEW_BROWSER_BINARY','C:/Program Files/Google/Chrome/Application/chrome.exe'),headless=True)
            page=browser.new_page(accept_downloads=True,offline=True,viewport={'width':1440,'height':1000});page.on('dialog',lambda d:d.accept())
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto((self.root/'analysis/attention.html').as_uri());page.locator('#opinion').select_option('o')
            page.locator('#actor').fill('浏览器编辑');page.locator('#reason').fill('保存A范围')
            for kind in ['explicit','partial','related','undetermined','outside']:
                page.locator('#a-kind').select_option(kind)
                if kind not in {'outside','undetermined'}:page.locator('#a-item').select_option('a')
                page.locator('#a-scope').fill('合成范围'+kind);page.locator('#a-reason').fill('只描述给定关注，不判专业结论')
                page.locator('#a-save').focus();page.keyboard.press('Enter')
            for width in (1440,420):
                page.set_viewport_size({'width':width,'height':1000})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            patchfile=self.root/'download.json'
            def save():
                with page.expect_download() as d:page.locator('#download').focus();page.keyboard.press('Enter')
                d.value.save_as(patchfile);controller.apply_attention(patchfile);controller.recover_attention();page.reload();page.locator('#opinion').select_option('o')
            save()
            self.assertEqual(len(self.ws.state()['opinions'][0]['facets'][0]['a_links']),4)
            self.assertIn('内容相关',page.locator('#saved').inner_text())
            page.locator('#actor').fill('浏览器编辑');page.locator('#reason').fill('纠正关联范围')
            page.locator('#a-link').select_option('a_links:0');page.locator('#a-scope').fill('纠正后的范围');page.locator('#a-save').click();save()
            self.assertEqual(self.ws.state()['opinions'][0]['facets'][0]['a_links'][-1]['scope'],'纠正后的范围')
            page.locator('#actor').fill('浏览器编辑');page.locator('#reason').fill('清空最后一条也保存')
            while page.locator('#a-link option').count()>1:
                page.locator('#a-link').select_option(index=1);page.locator('#a-remove').focus();page.keyboard.press('Enter')
            save()
            f=self.ws.state()['opinions'][0]['facets'][0];self.assertEqual(f['a_links'],[]);self.assertEqual(f['outside'],[])
            self.assertEqual(page.locator('#a-link option').count(),1)
            self.assertEqual(self.ws.state()['opinions'][0]['facets'][1],untouched)
            dest=Path(os.environ.get('ATTENTION_T3_EVIDENCE_DIR',self.root/'screens'));dest.mkdir(parents=True,exist_ok=True)
            for width in (1440,420):
                page.set_viewport_size({'width':width,'height':1000});page.locator('#a-save').scroll_into_view_if_needed();page.screenshot(path=str(dest/('a-controls-'+str(width)+'.png')))
            self.assertEqual(errors,[]);browser.close()

    def test_same_version_cannot_change_meaning_but_equal_reference_can_rebind(self):
        import json
        from reviewproto.core import ReviewError
        source=self.root/'replacement.json'
        ref=copy.deepcopy(self.state['a_reference'])
        source.write_text(json.dumps({'schema':'attention-a-input/1','a_reference':ref}),encoding='utf-8')
        self.ws.apply(self.patch(edits=[self.op()]))
        self.ws.import_a(source,actor='编辑',reason='显式绑定相同快照')
        source.unlink()
        self.assertEqual(self.ws.state()['a_material_status'],'needs_revalidation')
        other=self.root/'new-location.json';other.write_text(json.dumps({'schema':'attention-a-input/1','a_reference':ref}),encoding='utf-8')
        self.ws.import_a(other,actor='编辑',reason='旧文件失读后明确恢复同参照绑定')
        self.assertEqual(self.ws.state()['material_status'],'current')
        bad=copy.deepcopy(ref);bad['items'][0]['text']='另一含义'
        other.write_text(json.dumps({'schema':'attention-a-input/1','a_reference':bad}),encoding='utf-8')
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_A_VERSION'):self.ws.import_a(other,actor='编辑',reason='不能同版本换含义')
        self.assertEqual(self.ws.state()['revision'],3)
        self.assertEqual(self.ws.state()['a_reference'],ref)

    def test_six_synthetic_structures_keep_specific_a_and_outside_destinations(self):
        import json
        cases=json.loads((Path(__file__).parent/'fixtures/synthetic_attention_a_cases.json').read_text(encoding='utf-8'))['cases']
        target=AttentionWorkspace(self.root/'six');self.addCleanup(target.close)
        items=[dict(id=i,text=t,locator='synthetic:'+i,part_id=p) for i,t,p in [('method','可以说明样本组织','m'),('result','可以提供结果数据','r'),('citation','规范著录书目','o'),('background','说明问题的背景','b'),('wording','使用准确的学术措辞','o')]]
        state=target.build({'schema':'attention-input/1','records':[dict(anchor=c['id'],text=c['text'],visibility='author_visible') for c in cases],'a_reference':dict(version='six-v1',parts=[dict(id=i,label=i) for i in ['m','r','o','b']],items=items)})
        edits=[]
        for c,r in zip(cases,state['records']):
            ev=dict(source_id=r['source_id'],section_id=c['id'],start=0,end=len(c['text']),quote=c['text']);facets=[]
            for i,f in enumerate(c['facets']):
                common=dict(scope=f['scope'],reason='仅对应所述范围；具体偏好与来源疑虑不被宽泛条目吸收',evidence=[ev],status='working')
                facets.append(dict(facet_id=c['id']+str(i),interpretation=f['scope'],evidence=[ev],status='working',a_links=[dict(common,a_item_id=a,version='six-v1',kind=k) for a,k in f['links']],outside=[common] if f['outside'] else []))
            edits.append(dict(opinion_id=c['id'],record_id=r['record_id'],interpretation=c['id'],status='working',facets=facets))
        patch=dict(schema='attention-patch/2',analysis_id=state['analysis_id'],base_revision=0,actor='合成编辑',reason='保留六类反例的具体内容范围',edits=edits)
        target.apply(patch);target.apply(patch)
        saved=target.recover();self.assertEqual(saved['revision'],1)
        actual=[[[l['a_item_id'] for l in f['a_links']] for f in o['facets']] for o in saved['opinions']]
        self.assertEqual(actual,[[['method'],['result']],[[],['citation']],[[]],[['background']],[['wording'],[]],[[]]])
        self.assertEqual([[bool(f['outside']) for f in o['facets']] for o in saved['opinions']],[[False,False],[True,False],[True],[True],[False,True],[True]])
        self.assertEqual(saved['opinions'][3]['facets'][0]['a_links'][0]['kind'],'related')

    def test_cli_import_binds_source_and_bad_source_or_conflict_cannot_partially_save(self):
        import json,subprocess,sys
        from reviewproto.core import ReviewError,digest
        from reviewproto.attention_a import prepare_import
        source=self.root/'source.txt';source.write_text('可以保留例子及条件',encoding='utf-8')
        ref=copy.deepcopy(self.state['a_reference']);ref['version']='cli-v2'
        manifest=self.root/'manifest.json';payload=dict(schema='attention-a-input/1',a_reference=ref,source=dict(path='source.txt',fingerprint=digest(source.read_bytes())))
        manifest.write_text(json.dumps(payload),encoding='utf-8')
        cmd=[sys.executable,'-m','reviewproto','attention-import-a',str(manifest),'--workspace',str(self.root/'analysis'),'--actor','合成编辑','--reason','CLI接续']
        result=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('revision=1 material=current',result.stdout)
        ref['version']='cli-v3';manifest.write_text(json.dumps(payload),encoding='utf-8')
        patch=prepare_import(manifest,self.ws.state(),'合成编辑','过期事务')
        self.ws.import_a(manifest,actor='合成编辑',reason='先保存另一事务')
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_CONFLICT'):self.ws.apply(patch)
        source.write_text('上游变化',encoding='utf-8')
        ref['version']='cli-v4';manifest.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaisesRegex(ReviewError,'E_ATTENTION_A_SOURCE'):self.ws.import_a(manifest,actor='合成编辑',reason='错误来源不可保存')
        self.assertEqual(self.ws.state()['revision'],2)
        self.assertEqual(self.ws.state()['a_reference']['version'],'cli-v3')
