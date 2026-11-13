'use strict';
const state = JSON.parse(document.getElementById('attention-data').textContent);
const el = id => document.getElementById(id);
const edits = new Map();
let evidence = null;
let dirty = false;
const write = (id, text) => { el(id).textContent = text; };
const option = (select, text, value) => { const o = document.createElement('option'); o.textContent = text; o.value = value; select.append(o); };
const section = () => record().sections.find(s=>s.section_id===el('section').value);
const record = () => state.records.find(r => r.record_id === el('record').value);
function showEvidence(ev) { evidence = ev; write('evidence', ev ? '已选证据：' + ev.quote : '尚未选择证据'); }
function chooseOpinion() {
 const o = edits.get(el('opinion').value) || state.opinions.find(o => o.opinion_id === el('opinion').value);
 el('interpretation').value = o ? o.interpretation : ''; el('status').value = o ? o.status : 'working';
 showEvidence(o ? o.evidence[0] : null);
}
function chooseRecord() {
 el('section').replaceChildren(); record().sections.forEach(s=>option(el('section'),s.section_id,s.section_id)); chooseSection();
}
function chooseSection() {
 const r = record(), sec=section(); write('source', sec.text); write('locator', (r.kind === 'transcription' ? '可见转录锚点（不是Word位置）：' : '冻结普通分区：') + sec.section_id + ' · ' + JSON.stringify(sec.locator));
 el('scores').replaceChildren(); r.scores.forEach(s => {const p=document.createElement('p'); p.textContent=s.label+'：'+s.raw_value; el('scores').append(p);});
 el('opinion').replaceChildren(); option(el('opinion'),'新建解释','');
 state.opinions.filter(o=>o.record_id===r.record_id && o.evidence.some(e=>e.section_id===sec.section_id)).forEach(o=>option(el('opinion'),o.interpretation,o.opinion_id));
 el('passage').replaceChildren(); option(el('passage'),'请选择有依据的原话片段','');
 let start=0; sec.text.split(/(?<=[。！？\n])/u).forEach(t=>{const n=Array.from(t).length;if(t.trim())option(el('passage'),t,String(start)+':'+String(start+n)); start+=n;}); chooseOpinion();
}
el('passage').onchange=()=>{if(!el('passage').value){showEvidence(null);return;}const [start,end]=el('passage').value.split(':').map(Number);showEvidence({source_id:record().source_id,section_id:section().section_id,start,end,quote:Array.from(section().text).slice(start,end).join('')});};
el('capture').onclick=()=>{
 const s=window.getSelection(); const node=el('source').firstChild;
 if(!s || !node || s.anchorNode!==node || s.focusNode!==node || s.isCollapsed){write('message','请在原话中选择文字，或用原话片段菜单。');return;}
 const a=Math.min(s.anchorOffset,s.focusOffset),b=Math.max(s.anchorOffset,s.focusOffset),text=section().text;
 showEvidence({source_id:record().source_id,section_id:section().section_id,start:Array.from(text.slice(0,a)).length,end:Array.from(text.slice(0,b)).length,quote:text.slice(a,b)});write('message','');
};
el('stage').onclick=()=>{
 if(!evidence || !el('interpretation').value.trim() || !el('actor').value.trim() || !el('reason').value.trim()){write('message','请选择原话证据，并填写解释、修改者和修改理由。');return;}
 const old=state.opinions.find(o=>o.opinion_id===el('opinion').value);
 const staged=edits.get(el('opinion').value);
 const id=old?old.opinion_id:staged?staged.opinion_id:'op-'+crypto.randomUUID();
 edits.set(id,{opinion_id:id,facet_id:old?old.facet_id:staged?staged.facet_id:'f-'+crypto.randomUUID(),record_id:record().record_id,evidence:[evidence],interpretation:el('interpretation').value,status:el('status').value});
 if(!old && !staged){option(el('opinion'),el('interpretation').value,id);el('opinion').value=id;}
 write('draft','未应用草稿：'+edits.size+'项；已保存修订仍为 '+state.revision);dirty=false;el('download').disabled=false;write('message','草稿尚未保存到分析包。');
};
el('download').onclick=()=>{
 const patch={schema:'attention-patch/1',analysis_id:state.analysis_id,base_revision:state.revision,actor:el('actor').value,reason:el('reason').value,edits:[...edits.values()]};
 const url=URL.createObjectURL(new Blob([JSON.stringify(patch,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='attention-draft.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);write('message','已下载草稿，尚未应用保存。请在本机窗口应用后重开。');
};
write('revision','已保存修订 '+state.revision+' · 规则 '+state.rules_version);write('material',state.material_status==='current'?'输入绑定有效；原话和A参照已冻结。':'来源已变化或不可读：保留旧快照，待重新核对；禁止继续应用。');
if(state.material_status!=='current'){el('stage').disabled=true;}
state.records.forEach((r,i)=>option(el('record'),'记录 '+(i+1)+' · '+r.anchor,r.record_id));
write('a-version','版本 '+state.a_reference.version+'；仅作内容参照，不表示强制要求。');
for(const a of state.a_reference.items){const p=document.createElement('p');p.textContent=a.text+' · '+a.locator;el('a-items').append(p);}
if(!state.opinions.length)write('saved','尚无已保存解释。请选择证据创建，整条评语不会自动成为已理解观点。');
const statusNames={working:'工作解释',needs_review:'待核对',confirmed:'已核对分析',withdrawn:'撤回'};
for(const o of state.opinions){const p=document.createElement('p');p.textContent=o.interpretation+' · '+statusNames[o.status]+' · 原话：'+o.evidence.map(e=>e.quote).join(' / ');el('saved').append(p);}
if(!state.history.length)write('history','尚无修改修订。');
for(const h of state.history){const p=document.createElement('p');p.textContent='修订 '+h.revision+' · '+h.actor+' · '+h.reason;el('history').append(p);}
el('record').onchange=chooseRecord;el('section').onchange=chooseSection;el('opinion').onchange=chooseOpinion;chooseRecord();
for(const id of ['interpretation','status','actor','reason'])el(id).addEventListener('input',()=>{dirty=true;write('draft','表单有未加入草稿的更改；已保存修订仍为 '+state.revision);el('download').disabled=true;});
window.addEventListener('beforeunload',e=>{if(edits.size || dirty){e.preventDefault();e.returnValue='';}});
