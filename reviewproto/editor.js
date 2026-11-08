/* Embedded by render.py: private drafts live only in this document's memory. */
'use strict';
const el=id=>document.getElementById(id), clone=value=>structuredClone(value);
const base=JSON.parse(el('base').value), sections=JSON.parse(el('sections-data').value);
let draft={...clone(base),edits:[],creates:[]}, active=null, captured=null, advancedDirty=false, dirty=false;
const scalar=['status','direction','object','action','interpretation','speech_function','requirement_strength','severity','negation'];
function message(text){el('message').textContent=text;}
function freshId(){return 'human-'+crypto.randomUUID();}
function cleanFields(){return {status:'needs_review',interpretation:'unknown',object:'unknown',attributes:[],direction:'unknown',speech_function:'unknown',requirement_strength:'unknown',severity:'unknown',action:'unknown',conditions:[],alternatives:[],relations:[],reasons:[],negation:'unknown',concept_ids:[],clause_links:[]};}
function entries(){return [...draft.edits,...draft.creates];}
function current(){return entries().find(v=>v.candidate_id===active);}
function sectionOf(item){return item.section_id||item.fields.evidence[0].section_id;}
function ready(){if(advancedDirty){message('高级 JSON 尚未载入；请先点击“载入高级 JSON 到表单”，或直接下载 JSON。');return false;}return true;}
function publish(){draft.actor=el('actor').value;draft.reason=el('reason').value;el('patch').value=JSON.stringify(draft,null,2);dirty=true;}
function option(select,value,label=value){const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o);}
function queue(){const list=el('draft-list');list.replaceChildren();for(const item of entries())option(list,item.candidate_id,(draft.creates.includes(item)?'新增 · ':'修改 · ')+item.candidate_id+' · '+item.fields.object);list.value=active||'';}
function sourcePane(sid){el('add-section').value=sid;el('source-pane').textContent=sections.find(s=>s.section_id===sid)?.text||'';el('source-pane').dataset.section=sid;captured=null;el('captured-quote').textContent='尚未捕获';}
function selectExisting(id){if(!ready())return;let item=entries().find(v=>v.candidate_id===id);if(!item){if(draft.creates.some(v=>(v.replaces||[]).includes(id))){message('父项已由拆分草稿替换，请编辑子观点或删除拆分草稿。');return;}const saved=base.edits.find(v=>v.candidate_id===id);if(!saved)return;item=clone(saved);item.fields={...cleanFields(),...item.fields};draft.edits.push(item);}active=id;show();publish();}
function show(){const item=current();queue();el('delete-draft').disabled=!item;for(const id of scalar)el(id).value=item?.fields[id]??(id==='status'?'needs_review':'unknown');if(item){sourcePane(sectionOf(item));renderRows();}else{for(const id of ['evidence-list','reasons-rows','conditions-rows','alternatives-rows'])el(id).replaceChildren();}}
function mutate(callback,redraw=false){if(!ready()||!current())return;callback(current().fields);if(redraw)renderRows();queue();publish();}
function control(parent,label,key,value,choices,change){const wrap=document.createElement('label');wrap.append(document.createTextNode(label+' '));const input=document.createElement(choices?'select':'input');input.dataset.key=key;if(choices)for(const choice of choices)option(input,choice);input.value=value;input.addEventListener('input',()=>{if(!ready()){input.value=value;return;}change(input.value);publish();});wrap.append(input);parent.append(wrap);return input;}
function removeButton(parent,callback){const b=document.createElement('button');b.type='button';b.textContent='删除';b.addEventListener('click',()=>mutate(callback,true));parent.append(b);}
function references(parent,record){const box=document.createElement('div');for(const [i,e] of current().fields.evidence.entries()){const label=document.createElement('label');label.className='reference';const c=document.createElement('input');c.type='checkbox';c.checked=record.evidence_indices.includes(i);c.addEventListener('change',()=>{if(!ready()){c.checked=!c.checked;return;}record.evidence_indices=c.checked?[...record.evidence_indices,i].sort((a,b)=>a-b):record.evidence_indices.filter(v=>v!==i);publish();});label.append(c,document.createTextNode('证据 '+(i+1)+'：'+e.quote));box.append(label);}parent.append(box);}
function allReferences(fields){return [...fields.reasons,...fields.conditions,...fields.alternatives.flatMap(g=>g.branches),...fields.relations,...fields.clause_links];}
function renderRows(){const fields=current().fields;const evidence=el('evidence-list');evidence.replaceChildren();fields.evidence.forEach((e,i)=>{const row=document.createElement('fieldset');const p=document.createElement('pre');p.textContent='证据 '+(i+1)+' ['+e.start+', '+e.end+')\n'+e.quote;row.append(p);removeButton(row,f=>{const refs=allReferences(f);if(refs.some(r=>r.evidence_indices.includes(i))){message('此证据仍被引用；请先移除理由、条件、分支或高级关系中的引用。');return;}if(f.evidence.length===1){message('至少保留一条证据。');return;}f.evidence.splice(i,1);for(const r of refs)r.evidence_indices=r.evidence_indices.map(n=>n>i?n-1:n);message('已删除未引用证据，其余引用已保持对应。');});evidence.append(row);});
for(const kind of ['reasons','conditions']){const pane=el(kind+'-rows');pane.replaceChildren();fields[kind].forEach((r,i)=>{const row=document.createElement('fieldset');control(row,kind==='reasons'?'理由':'条件','text',r.text,null,v=>r.text=v);control(row,'依据','provenance',r.provenance,['unknown','explicit','inferred'],v=>r.provenance=v);if(kind==='conditions')control(row,'含义','meaning',r.meaning,['unknown','known'],v=>r.meaning=v);references(row,r);removeButton(row,f=>f[kind].splice(i,1));pane.append(row);});}
const pane=el('alternatives-rows');pane.replaceChildren();fields.alternatives.forEach((g,i)=>{const row=document.createElement('fieldset');control(row,'关系','relation',g.relation,['unknown','conditional_branches','either_or'],v=>g.relation=v);control(row,'依据','provenance',g.provenance,['unknown','explicit','inferred'],v=>g.provenance=v);g.branches.forEach((b,j)=>{const branch=document.createElement('fieldset');const title=document.createElement('legend');title.textContent='分支 '+(j+1);branch.append(title);control(branch,'条件（未知填 unknown）','condition',b.condition,null,v=>b.condition=v);control(branch,'动作','action',b.action,null,v=>b.action=v);references(branch,b);row.append(branch);});removeButton(row,f=>f.alternatives.splice(i,1));pane.append(row);});}
for(const section of sections)option(el('add-section'),section.section_id,section.section_id+' · '+section.label+' · '+section.visibility);
for(const [id,label,choices] of [['interpretation','语义依据',['unknown','explicit','inferred']],['speech_function','话语功能',['unknown','evaluation','suggestion','requirement','question','description','mixed']],['requirement_strength','要求强度',['unknown','mandatory','recommended','optional']],['severity','严重性',['unknown','minor','major','critical']],['negation','否定原意',null]])control(el('semantic-axes'),label,id,'unknown',choices,()=>{}).id=id;
for(const id of scalar)el(id).addEventListener('input',()=>mutate(f=>f[id]=el(id).value));
for(const id of ['actor','reason'])el(id).addEventListener('input',()=>{if(ready())publish();});
el('candidate').addEventListener('change',()=>selectExisting(el('candidate').value));
for(const link of document.querySelectorAll('.edit-candidate'))link.addEventListener('click',()=>{el('candidate').value=link.dataset.candidate;selectExisting(link.dataset.candidate);});
el('draft-list').addEventListener('change',()=>{if(!ready()){el('draft-list').value=active;return;}active=el('draft-list').value;show();});
el('add-section').addEventListener('change',()=>sourcePane(el('add-section').value));
el('patch').addEventListener('input',()=>{advancedDirty=true;dirty=true;message('高级 JSON 有未载入修改。');});
function prepareAdvanced(p){
    const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
    const check=value=>{if(!value)throw Error();};
    check(object(p)&&Array.isArray(p.edits)&&Array.isArray(p.creates||[])&&p.source_id===base.source_id&&p.base_revision===base.base_revision);
    check(typeof p.actor==='string'&&typeof p.reason==='string');
    p.creates??=[];
    for(const item of [...p.edits,...p.creates]){
        check(object(item)&&typeof item.candidate_id==='string'&&object(item.fields));
        const saved=base.edits.find(e=>e.candidate_id===item.candidate_id);
        const edit=p.edits.includes(item);
        check(!edit||saved);
        item.fields={...cleanFields(),...(edit?saved.fields:{}),...item.fields};
        const f=item.fields;
        for(const key of scalar)check(typeof f[key]==='string');
        for(const key of ['evidence','reasons','conditions','alternatives','relations','clause_links','attributes','concept_ids'])check(Array.isArray(f[key]));
        check(f.evidence.length>0);
        const sid=edit?saved.fields.evidence[0].section_id:item.section_id;
        check(sections.some(v=>v.section_id===sid));
        for(const e of f.evidence){
            check(object(e)&&e.section_id===sid&&e.source_id===base.source_id&&typeof e.quote==='string');
            check(exact(sid,e.start,e.end).quote===e.quote);
        }
        for(const row of [...f.reasons,...f.conditions])check(object(row)&&typeof row.text==='string'&&typeof row.provenance==='string');
        for(const row of f.conditions)check(typeof row.meaning==='string');
        for(const group of f.alternatives){
            check(object(group)&&typeof group.relation==='string'&&typeof group.provenance==='string'&&Array.isArray(group.branches)&&group.branches.length>=2);
            for(const branch of group.branches)check(object(branch)&&typeof branch.condition==='string'&&typeof branch.action==='string');
        }
        for(const row of allReferences(f))check(object(row)&&Array.isArray(row.evidence_indices)&&row.evidence_indices.every(i=>Number.isInteger(i)&&i>=0&&i<f.evidence.length));
        if(!edit)for(const key of ['parent_ids','replaces'])check(item[key]===undefined||Array.isArray(item[key])&&item[key].every(v=>typeof v==='string'));
    }
    const values=[...p.edits,...p.creates];
    check(new Set(values.map(v=>v.candidate_id)).size===values.length);
    check(!p.edits.some(e=>p.creates.some(c=>(c.replaces||[]).includes(e.candidate_id))));
    return p;
}
el('import-advanced').addEventListener('click',()=>{
    try{
        // Validate and normalize a separate object before replacing any live
        // draft, active selection, audit input or ordinary form field.
        const next=prepareAdvanced(JSON.parse(el('patch').value));
        const values=[...next.edits,...next.creates];
        draft=next;
        active=values.some(v=>v.candidate_id===active)?active:values[0]?.candidate_id;
        el('actor').value=draft.actor;el('reason').value=draft.reason;
        advancedDirty=false;show();publish();
        message('已载入高级 JSON；普通表单保留未改的高级字段。');
    }catch(e){
        advancedDirty=false;
        el('patch').value=JSON.stringify(draft,null,2);
        message('JSON 结构或来源/修订不匹配，未载入；原草稿未覆盖，已恢复有效 JSON，可继续修改表单。');
    }
});
el('delete-draft').addEventListener('click',()=>{if(!ready())return;const item=current();if(!item)return;draft.creates=draft.creates.filter(v=>v!==item);draft.edits=draft.edits.filter(v=>v!==item);active=entries()[0]?.candidate_id||null;show();publish();message('已移出本页草稿队列；不会删除候选或任何已保存记录。');});
function exact(sid,a,b){const s=sections.find(s=>s.section_id===sid),chars=Array.from(s?.text||'');if(!s||!Number.isInteger(a)||!Number.isInteger(b)||a<0||b<=a||b>chars.length)throw Error();return {source_id:base.source_id,section_id:sid,start:a,end:b,quote:chars.slice(a,b).join(''),precision:'exact'};}
el('capture-selection').addEventListener('click',()=>{try{const selection=getSelection();if(!selection.rangeCount)throw Error();const r=selection.getRangeAt(0),pane=el('source-pane');if(!pane.contains(r.startContainer)||!pane.contains(r.endContainer))throw Error();const prefix=document.createRange();prefix.selectNodeContents(pane);prefix.setEnd(r.startContainer,r.startOffset);const a=Array.from(prefix.toString()).length;prefix.setEnd(r.endContainer,r.endOffset);const b=Array.from(prefix.toString()).length;const s=sections.find(v=>v.section_id===pane.dataset.section);if(Array.from(s.text).slice(a,b).join('')!==r.toString())throw Error();captured={section:s.section_id,start:a,end:b};el('captured-quote').textContent='['+a+', '+b+') '+(r.toString()||'（光标）');message('已捕获冻结原文位置；尚未添加观点或证据。');}catch(e){captured=null;el('captured-quote').textContent='未捕获';message('请选择同一个冻结原文框内的文字或光标；不能跨分区。');}});
function createFrom(e){const item={candidate_id:freshId(),section_id:e.section_id,parent_ids:[],replaces:[],fields:{...cleanFields(),evidence:[e]}};draft.creates.push(item);active=item.candidate_id;show();publish();message('已添加待核草稿；请填写语义字段，下载后仍须本地应用。');}
el('selection-create').addEventListener('click',()=>{if(!ready())return;try{if(!captured)throw Error();createFrom(exact(captured.section,captured.start,captured.end));}catch(e){message('请先捕获非空原文选区。');}});
el('selection-evidence').addEventListener('click',()=>{if(!ready())return;try{if(!captured||!current()||captured.section!==sectionOf(current()))throw Error();const e=exact(captured.section,captured.start,captured.end);mutate(f=>f.evidence.push(e),true);message('已追加同分区证据；现有证据编号保持。');}catch(e){message('请捕获当前观点同分区的非空原文选区。');}});
function splitAt(n){if(!ready())return;try{const item=current(),e=item.fields.evidence[0],length=Array.from(e.quote).length;if(!Number.isInteger(n)||n<=0||n>=length||draft.creates.includes(item))throw Error();if(item.fields.evidence.length!==1){message('拆分只处理单条证据；多段证据请先核对并用补录分别建立观点。');return;}const pieces=[[e.start,e.start+n],[e.start+n,e.end]].map(([a,b])=>({candidate_id:freshId(),section_id:e.section_id,parent_ids:[item.candidate_id],replaces:[item.candidate_id],fields:{...cleanFields(),evidence:[exact(e.section_id,a,b)]}}));draft.edits=draft.edits.filter(v=>v!==item);draft.creates.push(...pieces);active=pieces[0].candidate_id;show();publish();message('已拆成两个待核草稿；父记录将保留。两条语义均已清空，请在队列逐条补充，核对条件与理由。');}catch(e){message('拆分点必须在已有观点首条证据内部；新增草稿请删除后重新补录。');}}
el('selection-split').addEventListener('click',()=>{if(!captured||!current()||captured.section!==sectionOf(current())){message('请捕获当前观点同分区的选区或光标。');return;}splitAt(captured.end-current().fields.evidence[0].start);});
el('split').addEventListener('click',()=>{const before=draft.creates.length;splitAt(Number(el('split-offset').value));if(draft.creates.length>before)el('patch').closest('details').open=true;});
el('add-opinion').addEventListener('click',()=>{if(!ready())return;try{createFrom(exact(el('add-section').value,Number(el('add-start').value),Number(el('add-end').value)));el('patch').closest('details').open=true;}catch(e){message('请核对分区与 Unicode 起止偏移。');}});
for(const kind of ['reason','condition'])el('add-'+kind).addEventListener('click',()=>mutate(f=>f[kind+'s'].push({text:'unknown',provenance:'unknown',evidence_indices:[0],...(kind==='condition'?{meaning:'unknown'}:{})}),true));
el('add-alternative').addEventListener('click',()=>mutate(f=>f.alternatives.push({relation:'unknown',provenance:'unknown',branches:[{condition:'unknown',action:'unknown',evidence_indices:[0]},{condition:'unknown',action:'unknown',evidence_indices:[0]}]}),true));
el('download').addEventListener('click',()=>{try{const patch=JSON.parse(el('patch').value);if(!patch.actor?.trim()||!patch.reason?.trim())throw Error();const blob=new Blob([JSON.stringify(patch,null,2)+'\n'],{type:'application/json;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='patch.json';a.click();URL.revokeObjectURL(a.href);message('已下载草稿补丁；尚未应用。请在本机入口选择此文件应用，再重新打开报告。');}catch(e){message('请检查 JSON、修改人及审计理由。');}});
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
if(base.edits.length)selectExisting(base.edits[0].candidate_id);else{sourcePane(sections[0]?.section_id);publish();}
dirty=false;
