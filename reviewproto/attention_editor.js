'use strict';
const state = JSON.parse(document.getElementById('attention-data').textContent);
const el = id => document.getElementById(id);
const clone = x => JSON.parse(JSON.stringify(x));
const dirtyGroups = new Set();
const edits = new Map(), themeEdits = new Map(), relationEdits = new Map();
const qualifierLabels={object:'对象',direction:'方向',degree:'程度',negation:'否定',reasons:'理由',conditions:'条件',actions:'动作',examples:'例示',alternatives:'备选'};
const qualifierKeys = ['object','direction','degree','negation','reasons','conditions','actions','examples','alternatives'];
const statusNames = {working:'工作解释',needs_review:'待核对',confirmed:'已核对分析',withdrawn:'撤回',superseded:'已被替换'};
let evidence = null, facetEvidence = [], selectedChanged = false, endpoints = [], relationEvidence = [], dirty = false, rich = false;
const write = (id,text) => { el(id).textContent = text; };
const option = (select,text,value) => {const o=document.createElement('option');o.textContent=text;o.value=value;select.append(o);};
const record = () => state.records.find(r=>r.record_id===el('record').value);
const section = () => record().sections.find(s=>s.section_id===el('section').value);
const allOpinions = () => [...state.opinions.filter(o=>!edits.has(o.opinion_id)), ...edits.values()];
const allThemes = () => [...state.themes.filter(t=>!themeEdits.has(t.theme_id)), ...themeEdits.values()];
const allRelations = () => [...state.relations.filter(r=>!relationEdits.has(r.relation_id)), ...relationEdits.values()];
const replaced = o => allOpinions().some(n=>(n.replaces||[]).includes(o.opinion_id));
const active = o => !['superseded','withdrawn'].includes(o.status) && !replaced(o);
const currentOpinion = () => allOpinions().find(o=>o.opinion_id===el('opinion').value);
const currentFacet = () => currentOpinion()?.facets.find(f=>f.facet_id===el('facet').value);
const uuid = prefix => prefix+'-'+crypto.randomUUID();
function showEvidence(ev, changed=false) {
 evidence=ev;selectedChanged=changed;
 write('evidence',ev?'已选证据：'+ev.quote:'尚未选择证据');
 write('facet-evidence-list','本方面证据：'+facetEvidence.map(e=>e.quote).join(' / '));
}
function notice(text='草稿尚未保存到分析包。', group='facet') {
 dirtyGroups.delete(group);dirtyGroups.delete('audit');dirty=dirtyGroups.size>0;
 write('draft','未应用草稿：'+edits.size+'项观点、'+themeEdits.size+'项主题、'+relationEdits.size+'项关系；已保存修订仍为 '+state.revision);
 if(dirty)write('draft',el('draft').textContent+'；仍有其他表单未加入草稿。');el('download').disabled=dirty;write('message',text);
}
function auditReady() {
 if(!el('actor').value.trim()||!el('reason').value.trim()){write('message','请填写修改者和修改理由，再加入草稿。');return false;}return state.material_status==='current';
}
function cleanOpinion(op) {
 const out={opinion_id:op.opinion_id,record_id:op.record_id,interpretation:op.interpretation,status:op.status,facets:clone(op.facets),replaces:clone(op.replaces||[])};
 if(op.legacy_aliases)out.legacy_aliases=clone(op.legacy_aliases);return out;
}
function refreshOpinions(selected='') {
 const options=allOpinions().filter(o=>o.record_id===record().record_id&&active(o));
 el('opinion').replaceChildren();option(el('opinion'),'新建观点','');
 el('merge-opinions').replaceChildren();
 options.forEach(o=>{option(el('opinion'),o.interpretation,o.opinion_id);option(el('merge-opinions'),o.interpretation,o.opinion_id);});
 el('opinion').value=selected;chooseOpinion();
}
function refreshEndpoints() {
 const selected=el('relation-facet').value;el('relation-facet').replaceChildren();
 for(const op of allOpinions().filter(active))for(const f of op.facets)if(!['withdrawn','superseded'].includes(f.status))option(el('relation-facet'),op.interpretation+' / '+f.interpretation,f.facet_id);
 if(currentFacet())el('relation-facet').value=currentFacet().facet_id;
 else if([...el('relation-facet').options].some(o=>o.value===selected))el('relation-facet').value=selected;
}
function chooseFacet() {
 const f=currentFacet();el('interpretation').value=f?f.interpretation:'';el('status').value=f?f.status:'working';el('facet-kind').value=f?.kind||'content';
 for(const key of qualifierKeys){const value=f?.qualifiers?.[key]||'';el(key).value=Array.isArray(value)?value.join('\n'):value;}
 el('function').value=f?.expression?.function||'';
 el('boilerplate').value=f?.expression?.boilerplate_candidate==null?'unknown':String(f.expression.boilerplate_candidate);
 facetEvidence=clone(f?.evidence||[]);showEvidence(facetEvidence[0]||null);
 write('members',(f?.themes||[]).map(m=>(allThemes().find(t=>t.theme_id===m.theme_id)?.label||m.theme_id)+' · '+statusNames[m.status]+' · '+m.reason).join('；'));
 refreshEndpoints();
}
function chooseOpinion() {
 const op=currentOpinion();el('facet').replaceChildren();option(el('facet'),'添加新方面','');
 if(op){op.facets.filter(f=>f.status!=='superseded').forEach(f=>option(el('facet'),f.interpretation,f.facet_id));if(op.facets.length)el('facet').value=op.facets[0].facet_id;}
 chooseFacet();
}
function chooseRecord() {
 el('section').replaceChildren();record().sections.forEach(s=>option(el('section'),s.section_id,s.section_id));chooseSection();
}
function chooseSection() {
 const r=record(),sec=section();write('source',sec.text);
 write('locator',(r.kind==='transcription'?'可见转录锚点（不是Word位置）：':'冻结普通分区：')+sec.section_id+' · '+JSON.stringify(sec.locator));
 el('scores').replaceChildren();r.scores.forEach(s=>{const p=document.createElement('p');p.textContent=s.label+'：'+s.raw_value;el('scores').append(p);});
 write('record-note',r.expression_note?'旧稿记录级工作说明（可含正文以外语境，未核为正文证据，不自动成为方面判断）：'+r.expression_note:'');
 el('passage').replaceChildren();option(el('passage'),'请选择有依据的原话片段','');
 let start=0;sec.text.split(/(?<=[。！？\n])/u).forEach(t=>{const n=Array.from(t).length;if(t.trim())option(el('passage'),t,start+':'+(start+n));start+=n;});
 refreshOpinions();
}
el('passage').onchange=()=>{
 if(!el('passage').value){showEvidence(null,true);return;}
 const [start,end]=el('passage').value.split(':').map(Number);
 showEvidence({source_id:record().source_id,section_id:section().section_id,start,end,quote:Array.from(section().text).slice(start,end).join('')},true);
};
el('capture').onclick=()=>{
 const selection=window.getSelection(),node=el('source').firstChild;
 if(!selection||!node||selection.anchorNode!==node||selection.focusNode!==node||selection.isCollapsed){write('message','请在原话中选择文字，或用原话片段菜单。');return;}
 const a=Math.min(selection.anchorOffset,selection.focusOffset),b=Math.max(selection.anchorOffset,selection.focusOffset),text=section().text;
 showEvidence({source_id:record().source_id,section_id:section().section_id,start:Array.from(text.slice(0,a)).length,end:Array.from(text.slice(0,b)).length,quote:text.slice(a,b)},true);
};
el('evidence-add').onclick=()=>{if(evidence&&!facetEvidence.some(e=>JSON.stringify(e)===JSON.stringify(evidence)))facetEvidence.push(clone(evidence));selectedChanged=false;showEvidence(evidence);};
function stageFacet() {
 if(!evidence||!el('interpretation').value.trim()){write('message','请选择原话证据，并填写解释、修改者和修改理由。');return null;}
 if(!auditReady())return null;
 const old=currentOpinion(),prior=currentFacet();
 const facet=prior?clone(prior):{facet_id:uuid('f'),themes:[],a_links:[],outside:[],legacy_aliases:[]};
 facet.interpretation=el('interpretation').value;facet.status=el('status').value;facet.kind=el('facet-kind').value;if(facet.kind!=='content')rich=true;
 facet.evidence=clone(selectedChanged?[evidence]:facetEvidence.length?facetEvidence:[evidence]);
 facet.qualifiers={...facet.qualifiers};
 for(const key of qualifierKeys){
  const value=el(key).value,previous=facet.qualifiers[key];
  facet.qualifiers[key]=Array.isArray(previous)&&previous.join('\n')===value?previous:value;
  if(value)rich=true;
 }
 facet.expression={function:el('function').value,boilerplate_candidate:el('boilerplate').value==='unknown'?null:el('boilerplate').value==='true'};
 if(facet.expression.function||facet.expression.boilerplate_candidate!==null)rich=true;
 // Empty values can be explicit corrections; a legacy edit cannot carry them.
 if(prior&&['kind','qualifiers','expression'].some(key=>JSON.stringify(prior[key])!==JSON.stringify(facet[key])))rich=true;
 const op=old?cleanOpinion(old):{opinion_id:uuid('op'),record_id:record().record_id,interpretation:facet.interpretation,status:'working',facets:[],replaces:[]};
 if(prior)op.facets[op.facets.findIndex(f=>f.facet_id===prior.facet_id)]=facet;else op.facets.push(facet);
 if(op.facets.length===1){op.interpretation=facet.interpretation;op.status=facet.status;}else rich=true;
 edits.set(op.opinion_id,op);refreshOpinions(op.opinion_id);el('facet').value=facet.facet_id;chooseFacet();notice();return op;
}
el('stage').onclick=stageFacet;
function replacement(op, facets) {
 return {opinion_id:uuid('op'),record_id:op.record_id,interpretation:facets.map(f=>f.interpretation).join('；'),status:'needs_review',replaces:[op.opinion_id],facets:facets.map(f=>({...clone(f),facet_id:uuid('f'),themes:[],a_links:[],outside:[],legacy_aliases:[],status:'needs_review'}))};
}
el('split').onclick=()=>{
 if(!auditReady())return;if(dirtyGroups.has('facet')){write('message','请先将当前方面的修改加入草稿，再拆分。');return;}const op=currentOpinion();
 if(!op||op.facets.length<2){write('message','请先为观点补录至少两个可分别核对的方面，再按方面拆分。');return;}
 const children=op.facets.filter(f=>f.status!=='withdrawn').map(f=>replacement(op,[f]));
 if(children.length<2){write('message','拆分需要至少两个未撤回方面。');return;}
 children.forEach(o=>edits.set(o.opinion_id,o));rich=true;refreshOpinions(children[0].opinion_id);notice('已拆分为新观点；旧身份与限定保留，旧关联待核，未转绑。');
};
el('merge').onclick=()=>{
 if(!auditReady())return;
 if(dirtyGroups.has('facet')){write('message','请先将当前方面的修改加入草稿，再归并。');return;}
 const selected=[...el('merge-opinions').selectedOptions].map(o=>allOpinions().find(x=>x.opinion_id===o.value));
 if(selected.length<2){write('message','请选择同记录的至少两个观点。');return;}
 const merged=replacement(selected[0],selected.flatMap(o=>o.facets));
 merged.replaces=selected.map(o=>o.opinion_id);edits.set(merged.opinion_id,merged);rich=true;
 refreshOpinions(merged.opinion_id);notice('已归并并保留各方面；旧关联待核，未转绑。');
};
function refreshThemes(selected='') {
 el('theme').replaceChildren();option(el('theme'),'新建主题','');
 el('theme-parents').replaceChildren();
 allThemes().forEach(t=>{option(el('theme'),t.label,t.theme_id);if(t.theme_id!==selected)option(el('theme-parents'),t.label,t.theme_id);});
 el('theme').value=selected;chooseTheme();
}
function chooseTheme() {
 const t=allThemes().find(t=>t.theme_id===el('theme').value);
 el('theme-label').value=t?.label||'';el('theme-definition').value=t?.definition||'';
 for(const o of el('theme-parents').options)o.selected=(t?.parent_ids||[]).includes(o.value);
}
el('theme-stage').onclick=()=>{
 if(!auditReady())return;
 if(!el('theme-label').value.trim()||!el('theme-definition').value.trim()){write('message','请填写主题名称和定义边界。');return;}
 const old=allThemes().find(t=>t.theme_id===el('theme').value);
 const t={theme_id:old?.theme_id||uuid('theme'),label:el('theme-label').value,definition:el('theme-definition').value,parent_ids:[...el('theme-parents').selectedOptions].map(o=>o.value),status:'working'};
 if(old?.legacy_aliases)t.legacy_aliases=clone(old.legacy_aliases);
 themeEdits.set(t.theme_id,t);rich=true;refreshThemes(t.theme_id);notice(undefined,'theme');
};
function member(withdraw) {
 if(!auditReady())return;const op=currentOpinion(),f=currentFacet(),tid=el('theme').value;
 if(!op||!f||!tid||!el('member-reason').value.trim()){write('message','请先加入方面草稿、选择主题并填写成员依据。');return;}
 const result=cleanOpinion(op),facet=result.facets.find(x=>x.facet_id===f.facet_id);
 const link={theme_id:tid,reason:el('member-reason').value,evidence:clone(evidence?[evidence]:f.evidence),status:withdraw?'withdrawn':'working'};
 const index=facet.themes.findIndex(m=>m.theme_id===tid);if(index<0)facet.themes.push(link);else facet.themes[index]=link;
 edits.set(op.opinion_id,result);rich=true;chooseFacet();notice(undefined,'member');
}
el('member-add').onclick=()=>member(false);el('member-withdraw').onclick=()=>member(true);
function showEndpoints() {el('endpoints').replaceChildren();endpoints.forEach((e,i)=>{const f=allOpinions().flatMap(o=>o.facets).find(f=>f.facet_id===e.facet_id);option(el('endpoints'),e.role+' · '+(f?.interpretation||e.facet_id),String(i));});write('relation-evidence-list',relationEvidence.map(e=>e.quote).join(' / '));}
function chooseRelation() {
 const r=allRelations().find(r=>r.relation_id===el('relation').value);
 for(const key of ['type','direction','scope','reading','ambiguity'])el('relation-'+key).value=r?.[key]||'';
 el('relation-status').value=r?.status||'working';endpoints=clone(r?.endpoints||[]);relationEvidence=clone(r?.evidence||[]);showEndpoints();
}
function refreshRelations(selected='') {el('relation').replaceChildren();option(el('relation'),'新建关系','');allRelations().forEach(r=>option(el('relation'),r.type+' · '+r.reading,r.relation_id));el('relation').value=selected;chooseRelation();}
el('endpoint-add').onclick=()=>{
 if(!el('relation-facet').value||!el('relation-role').value.trim()){write('message','请选择端点方面并填写角色。');return;}
 endpoints.push({facet_id:el('relation-facet').value,role:el('relation-role').value});showEndpoints();
};
el('endpoint-remove').onclick=()=>{const index=Number(el('endpoints').value);if(el('endpoints').value!=='')endpoints.splice(index,1);showEndpoints();};
el('relation-evidence').onclick=()=>{if(evidence&&!relationEvidence.some(e=>JSON.stringify(e)===JSON.stringify(evidence)))relationEvidence.push(clone(evidence));showEndpoints();};
el('relation-stage').onclick=()=>{
 if(!auditReady())return;
 if(!endpoints.length||(!relationEvidence.length&&!evidence)||['type','direction','scope','reading'].some(k=>!el('relation-'+k).value.trim())){write('message','请添加端点、选择原话证据，并填写类型、方向、范围和工作读法。');return;}
 const old=allRelations().find(r=>r.relation_id===el('relation').value);
 const r={relation_id:old?.relation_id||uuid('relation'),endpoints:clone(endpoints),evidence:clone(relationEvidence.length?relationEvidence:[evidence]),status:el('relation-status').value};
 for(const key of ['type','direction','scope','reading','ambiguity'])r[key]=el('relation-'+key).value;
 if(old?.legacy_aliases)r.legacy_aliases=clone(old.legacy_aliases);
 relationEdits.set(r.relation_id,r);rich=true;refreshRelations(r.relation_id);notice(undefined,'relation');
};
el('download').onclick=()=>{
 if(!auditReady()||dirty)return;
 const simple=!rich&&themeEdits.size===0&&relationEdits.size===0&&[...edits.values()].every(o=>o.facets.length===1&&!o.replaces.length);
 const patch={schema:simple?'attention-patch/1':'attention-patch/2',analysis_id:state.analysis_id,base_revision:state.revision,actor:el('actor').value,reason:el('reason').value,edits:[...edits.values()].map(o=>simple?{opinion_id:o.opinion_id,record_id:o.record_id,facet_id:o.facets[0].facet_id,evidence:o.facets[0].evidence,interpretation:o.facets[0].interpretation,status:o.facets[0].status}:o)};
 if(!simple){patch.themes=[...themeEdits.values()];patch.relations=[...relationEdits.values()];}
 const url=URL.createObjectURL(new Blob([JSON.stringify(patch,null,2)],{type:'application/json'})),a=document.createElement('a');
 a.href=url;a.download='attention-draft.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 write('message','已下载草稿，尚未应用保存。请在本机窗口应用后重开。');
};
write('revision','已保存修订 '+state.revision+' · 规则 '+state.rules_version);
write('material',state.material_status==='current'?(state.a_reference.items.length?'输入绑定有效；原话和A参照已冻结。':'输入绑定有效；B原话原分已冻结，A参照尚未导入。'):'来源已变化或不可读：保留旧快照，待重新核对；禁止继续应用。');
if(state.material_status!=='current')for(const id of ['stage','split','merge','theme-stage','member-add','member-withdraw','relation-stage'])el(id).disabled=true;
state.records.forEach((r,i)=>option(el('record'),'记录 '+(i+1)+' · '+r.anchor,r.record_id));
write('a-version',state.a_reference.items.length?'版本 '+state.a_reference.version+'；仅作内容参照，不表示强制要求。':'A工作参照尚未导入；当前仅显示B分析。');
function paragraph(id,text){const p=document.createElement('p');p.textContent=text;el(id).append(p);}
state.a_reference.items.forEach(a=>paragraph('a-items',a.text+' · '+a.locator));
if(!state.opinions.length)write('saved','尚无已保存解释。请选择证据创建，整条评语不会自动成为已理解观点。');
for(const o of state.opinions){
 paragraph('saved','记录 '+(state.records.find(r=>r.record_id===o.record_id)?.anchor||'未知')+' · '+o.interpretation+' · '+statusNames[o.status]+((o.replaces||[]).length?' · 替换前身已保留':''));
 for(const f of o.facets)paragraph('saved',(f.kind==='disposition'?'流程/处置方面：':'内容方面：')+f.interpretation+' · '+statusNames[f.status]+' · 原话：'+f.evidence.map(e=>e.quote).join(' / ')+' · 限定：'+Object.entries(f.qualifiers||{}).filter(([,v])=>v.length).map(([k,v])=>qualifierLabels[k]+'：'+(Array.isArray(v)?v.join('；'):v)).join('；')+' · 表达作用：'+(f.expression?.function||'未说明')+' · 套话候选：'+(f.expression?.boilerplate_candidate==null?'未判断':f.expression.boilerplate_candidate?'是':'否')+' · 主题成员：'+f.themes.map(m=>(state.themes.find(t=>t.theme_id===m.theme_id)?.label||m.theme_id)+' / '+statusNames[m.status]+' / '+m.reason).join('；'));
}
for(const t of state.themes)paragraph('saved-themes',t.label+' · '+t.definition+' · '+statusNames[t.status]+' · 定义版本 '+(t.version||1));
for(const r of state.relations)paragraph('saved-relations',r.type+' · '+r.endpoints.map(e=>e.role+'：'+(state.opinions.flatMap(o=>o.facets).find(f=>f.facet_id===e.facet_id)?.interpretation||e.facet_id)).join('；')+' · '+r.direction+' · 范围：'+r.scope+' · '+r.reading+' · '+r.ambiguity+' · '+statusNames[r.status]+' · 原话：'+r.evidence.map(e=>e.quote).join(' / '));
if(!state.history.length)write('history','尚无修改修订。');
state.history.forEach(h=>paragraph('history','修订 '+h.revision+' · '+h.actor+' · '+h.reason));
el('record').onchange=chooseRecord;el('section').onchange=chooseSection;el('opinion').onchange=chooseOpinion;el('facet').onchange=chooseFacet;el('theme').onchange=chooseTheme;el('relation').onchange=chooseRelation;
chooseRecord();refreshThemes();refreshRelations();
for(const id of ['interpretation','status','facet-kind','actor','reason',...qualifierKeys,'function','boilerplate','theme-label','theme-definition','theme-parents','member-reason','relation-type','relation-role','relation-direction','relation-scope','relation-reading','relation-ambiguity','relation-status'])el(id).addEventListener('input',()=>{dirtyGroups.add(['actor','reason'].includes(id)?'audit':id.startsWith('theme-')?'theme':id.startsWith('relation-')?'relation':id==='member-reason'?'member':'facet');dirty=true;write('draft','表单有未加入草稿的更改；已保存修订仍为 '+state.revision);el('download').disabled=true;});
window.addEventListener('beforeunload',e=>{if(edits.size||themeEdits.size||relationEdits.size||dirty){e.preventDefault();e.returnValue='';}});
