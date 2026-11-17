/* Offline saved-result views. Content classification comes from summarize(). */
(() => {
'use strict';
const base=JSON.parse(document.getElementById('attention-summary-data').textContent);
const positions=JSON.parse(document.getElementById('attention-position-data').textContent);
const $=id=>document.getElementById(id);
const labels={withdrawn:'撤回',superseded:'已被替换',working:'未核对',needs_review:'待核对',confirmed:'已核对分析',explicit:'明确对应',partial:'部分对应',related:'内容相关',undetermined:'暂未定',content:'内容关注',disposition:'流程或总体处置',reason:'理由',conditional_fallback:'条件备用动作',alternative:'备选路径',co_occurrence:'相伴表达'};
Object.assign(labels,{alternative_with_condition:'有条件的备选路径',coexisting_readings:'并存读法',shared_premise:'共同前提',alternative_with_minimum:'有最低动作的备选路径',suggestion_timing:'建议时机',declared_reason_scope:'明示理由范围',listed_ways_not_all_mandatory:'列举路径（非全部必做）',listed_ways_and_explicit_suggestion:'列举路径与明确建议',co_written_scope_unresolved:'共同表述（范围未决）'});
const name=v=>labels[v]||v||'未说明';
const recordLabel=id=>base.details[id]?.record.anchor||id;
const paperId=record=>record.paper_id??record.locator?.paper_id??null;
const short=value=>value.length>52?value.slice(0,52)+'…':value;
function readingTitle(value){const prefix=value.split('：')[0];return prefix.length>=10&&prefix.length<=72&&prefix!==value?prefix:value.length>100?value.slice(0,100)+'…':value;}
const aReferences=[base.a_reference,...(JSON.parse($('attention-data').textContent).a_reference_history||[]).map(h=>h.a_reference)];
function aTitle(id,version,compact=false){
 const reference=aReferences.find(a=>a.version===version),title=reference?.items.find(a=>a.id===id)?.text;
 const text=title||'原A条目（原文不可用）';
 return (compact?short(text):text)+(version&&version!==base.a_version?'（旧版 '+version+'）':!version?'（版本未说明）':'');
}
function aReading(c){
 const parts=c.a_items.map(a=>name(a.kind)+'：'+aTitle(a.id,a.version,true));
 const facet=base.details[c.record_id].facets.find(e=>e.facet.facet_id===c.facet_id).facet;
 const unassigned=(facet.a_links||[]).filter(a=>!['withdrawn','superseded'].includes(a.status)&&!base.a_reference.items.some(item=>item.id===a.a_item_id));
 for(const a of unassigned)parts.push(a.a_item_id?'待核对：'+aTitle(a.a_item_id,a.version,true):'A条目尚未确定');
 if(c.outside.length)parts.push(c.outside.includes('needs_review')?'清单外范围待核对':'含A清单外内容');
 return parts.join('；')||((base.a_reference.items||[]).length?'尚未标注A对应':'尚未导入A');
}
const facetLabel=c=>base.details[c.record_id].facets.find(e=>e.facet.facet_id===c.facet_id)?.facet.interpretation||c.facet_id;
const node=(tag,text,parent,attrs={})=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(parent)parent.append(e);return e;};
const unique=xs=>[...new Set(xs)].sort();
const controls=$('view-controls');
const picks={};
function pick(key,title,values){const l=node('label',title,controls),s=node('select',null,l,{id:'view-'+key});node('option','全部',s,{value:'*'});for(const [value,text] of values)node('option',text,s,{value});s.onchange=refresh;picks[key]=s;}
pick('record','记录筛选（改变分母）',Object.entries(base.details).map(([id,d])=>[id,d.record.anchor||id]));
pick('paper','材料筛选（改变分母）',unique(Object.values(base.details).map(d=>JSON.stringify(paperId(d.record)))).map(v=>[v,JSON.parse(v)??'未知材料组']));
for(const [key,title,values] of [['function','表达作用',base.contributions.map(c=>c.expression.function||'未说明')],['direction','判断方向',base.contributions.flatMap(c=>c.directions)],['status','方面核对状态',base.contributions.map(c=>c.status)]])pick(key,title,unique(values).map(v=>[v,name(v)]));
pick('boiler','套话候选',[['true','是候选'],['false','非候选'],['null','未判断']]);
node('button','清除筛选',controls,{type:'button'}).onclick=()=>{Object.values(picks).forEach(s=>s.value='*');refresh();};
const style=node('style',`#attention-views input[type=checkbox]{width:auto}#attention-views table{border-collapse:collapse;min-width:36rem;width:100%;font-variant-numeric:tabular-nums}#attention-views th,#attention-views td{border:1px solid #c8d0da;padding:.5rem;text-align:left;vertical-align:top}#attention-views .view-scroll{max-width:100%;overflow:auto}#attention-views th{min-width:9rem}#attention-views th:first-child{min-width:4rem}#attention-views td a{display:block;margin:.2rem 0}#attention-views td button{padding:.2rem;margin:0;text-align:left}#attention-views svg{min-width:960px;width:100%;display:block}#attention-views svg text{font:14px system-ui;fill:#17212e}#attention-views :target{outline:2px solid #315879}#attention-views blockquote{margin:.5rem 0;padding:.7rem;background:#eef1f5;white-space:pre-wrap}#attention-views [hidden]{display:none}`,document.head);
let current;
const anchor=rid=>'view-record-'+encodeURIComponent(rid);
const facetAnchor=fid=>'view-facet-'+encodeURIComponent(fid);
const relationAnchor=id=>'view-relation-'+encodeURIComponent(id);
function link(parent,text,target){return node('a',text,parent,{href:'#'+target});}
function metric(parent,cs,N){const ids=unique(cs.map(c=>c.record_id));node('span',ids.length+'/'+N+(N?'':'（无比例）')+' · ',parent);if(!ids.length)node('span','无命中记录',parent);ids.forEach(id=>{link(parent,recordLabel(id),anchor(id));node('span',' ',parent);});}
function row(parent,title,cs){const li=node('li',null,parent);node('strong',title+' ',li);metric(li,cs,current.ids.length);}
function group(title,rows){let root=$('view-summary');if(title.startsWith('A部分')||title==='A条目'){root=node('details',null,root);node('summary',title+'（展开各关系种类与记录集合）',root);}else node('h3',title,root);const ul=node('ul',null,root);for(const [title,cs] of rows)row(ul,title,cs);}
function evidence(parent,entries){for(const e of entries||[]){const b=node('blockquote',e.quote,parent);node('small','出处：'+(e.section_id||'未说明')+' · 字符 '+e.start+'–'+e.end,b);}}
function explain(parent,title,value){if(value!=null&&value!==''&&(!Array.isArray(value)||value.length))node('p',title+'：'+(Array.isArray(value)?value.join('；'):value),parent);}
function overview(){
 const root=node('div',null,$('view-summary'),{id:'view-overview',role:'region','aria-label':'当前关注概览'});
 node('h3','当前关注概览',root);
 node('p','已保存修订 '+base.revision+' · 分母 '+current.ids.length+' 条评语记录 · A版本 '+((base.a_reference.items||[]).length?base.a_version:'A未导入'),root);
 node('p',current.ids.length+' 条记录 · '+current.ids.reduce((n,id)=>n+(base.details[id].record.scores||[]).length,0)+' 项原分 · '+unique(current.cs.map(c=>c.opinion_id)).length+' 个观点 / '+unique(current.cs.map(c=>c.facet_id)).length+' 个方面 · '+Object.keys(base.theme_definitions).length+' 个主题定义 · '+current.relations.length+' 个当前关系组',root);
 if(!current.cs.length)node('p','当前集合尚未形成有效观点方面；材料导入不等于完成分析。若已设置筛选，可清除筛选查看。请在下方原话区补录并保存。',root);
 if(!(base.a_reference.items||[]).length)node('p','A未导入：可先整理B，之后在本机窗口导入A参照版本；不把无A当作清单外。',root);
 node('p','A结构：'+(base.a_reference.parts||[]).length+' 个部分 / '+(base.a_reference.items||[]).length+' 个条目',root);
 node('p','B输入状态：'+({current:'绑定有效',needs_revalidation:'来源待核'}[base.b_material_status||base.material_status]||'未说明')+' · A输入状态：'+((base.a_reference.items||[]).length?({current:'绑定有效',needs_revalidation:'来源待核'}[base.a_material_status||base.material_status]||'未说明'):'未导入'),root);
 if(base.material_status==='needs_revalidation')node('p','来源失效：以下保留旧快照。B有效时，A可导入版本接续；B须恢复原绑定文件，或为变化材料另建分析，不迁移旧标注。',root);
 node('p','页面为保存快照，不实时轮询来源；本机打开、恢复或应用时重查，成功后重开本页。下载修改文件不更新概览。',root);
 const ul=node('ul',null,root),content=current.cs.filter(c=>c.kind==='content');
 row(ul,'观点方面记录覆盖',current.cs);
 row(ul,'内容主题记录并集',content.filter(c=>c.theme_ids.length));
 for(const kind of ['explicit','partial','related','undetermined','needs_review'])row(ul,'A'+name(kind)+'记录并集',content.filter(c=>c.a_items.some(a=>a.kind===kind)||c.a_unassigned.includes(kind)));
 for(const status of ['working','needs_review','confirmed'])row(ul,'内容方面'+name(status)+'记录',content.filter(c=>c.status===status));
 const endpoints=new Set(current.relations.flatMap(r=>r.endpoints.map(e=>e.facet_id)));
 row(ul,'关系端点记录并集',current.cs.filter(c=>endpoints.has(c.facet_id)));
 node('p','覆盖按记录去重，各类可重叠；观点、方面与关系组数是辅助规模。主题定义不等于命中，未核对解释不等于已核对；各主题、A部分/条目和关系类型的明细见下方。',root);
}
// Selection is a reading cursor; it never changes the summary denominator.
let selectedRecord='', selectedFacet='', sourceOpen=false;
const recordOrder=JSON.parse($('attention-data').textContent).records.map(r=>r.record_id);
const shell=node('div',null,null,{id:'focus-shell'});
$('view-detail').before(shell);
const list=node('aside',null,shell,{id:'focus-list','aria-label':'评语列表'});
const center=node('main',null,shell,{id:'focus-reading','aria-label':'所选评语'});
const sourcePanel=node('aside',null,shell,{id:'focus-source','aria-label':'来源查证',hidden:''});
function selectRecord(id){
 if(!current.ids.includes(id))return;
 selectedRecord=id;selectedFacet='';sourceOpen=false;focusReading();list.querySelector('[aria-pressed=true]')?.focus({preventScroll:true});
}
function showSource(c){selectedFacet=c?.facet_id||'';sourceOpen=true;focusReading();sourcePanel.tabIndex=-1;sourcePanel.focus({preventScroll:true});if(window.innerWidth<901)sourcePanel.scrollIntoView({block:'start'});}
function focusReading(){
 if(!current.ids.includes(selectedRecord))selectedRecord=current.ids[0]||'';
 window.AttentionPositions.render({recordIds:current.ids,facetIds:current.cs.map(c=>c.facet_id),expressionFilters:Object.fromEntries(Object.entries(picks).map(([k,s])=>[k,s.value])),selectedRecordId:selectedRecord});
 list.replaceChildren();center.replaceChildren();sourcePanel.replaceChildren();
 node('h2','评语列表（'+current.ids.length+'）',list);
 for(const id of current.ids){
  const r=base.details[id].record,cs=current.cs.filter(c=>c.record_id===id);
  const b=node('button',null,list,{type:'button','aria-pressed':String(id===selectedRecord)});
  node('strong',r.anchor||id,b);node('small',cs.some(c=>c.status!=='confirmed')?'待核对':cs.length?'已核对':'未整理',b);
  node('span',(r.sections||[{text:r.text}]).map(s=>s.text).join(' '),b,{class:'focus-excerpt'});
  b.onclick=()=>selectRecord(id);
 }
 if(!selectedRecord){node('h2','当前筛选没有记录',center);node('p','调整筛选后继续阅读。',center);sourcePanel.hidden=true;return;}
 const r=base.details[selectedRecord].record,cs=current.cs.filter(c=>c.record_id===selectedRecord);
 const pager=node('nav',null,center,{'aria-label':'评语切换',class:'focus-pager'}),index=current.ids.indexOf(selectedRecord);
 const previous=node('button','上一份',pager,{type:'button'});previous.disabled=index===0;previous.onclick=()=>selectRecord(current.ids[index-1]);
 node('span',String(index+1).padStart(2,'0')+' / '+String(current.ids.length).padStart(2,'0'),pager);
 const next=node('button','下一份',pager,{type:'button'});next.disabled=index===current.ids.length-1;next.onclick=()=>selectRecord(current.ids[index+1]);
 const heading=node('div',null,center,{class:'focus-heading'});node('h2',r.anchor||selectedRecord,heading);
 node('span',cs.some(c=>c.status!=='confirmed')?'待核对':cs.length?'已核对分析':'未整理',heading,{class:'focus-state'});
 if(!cs.length)node('p','尚无命中解释；本条仍计入分母。可查看原话，或进入修改补录。',center);
 cs.forEach((c,i)=>{
  const entry=base.details[c.record_id].facets.find(e=>e.facet.facet_id===c.facet_id),f=entry.facet;
  const concern=node('section',null,center,{class:'focus-concern'});
  const title=node('button','关注点 '+(i+1)+'：'+(f.qualifiers?.object||readingTitle(f.interpretation)),concern,{type:'button','aria-label':'查证关注点 '+(i+1),class:'focus-concern-title'});
  title.onclick=()=>showSource(c);
  if(f.qualifiers?.object||readingTitle(f.interpretation)!==f.interpretation)node('p',f.interpretation,concern);
  for(const [key,label] of Object.entries({conditions:'条件',negation:'否定',degree:'程度',reasons:'理由',actions:'动作',alternatives:'备选',examples:'例示'}))explain(concern,label,f.qualifiers?.[key]);
 });
 const a=node('section',null,center,{class:'focus-a'});node('h3','与参考方向 A 的对应关系',a);
 for(const c of cs){const f=base.details[c.record_id].facets.find(e=>e.facet.facet_id===c.facet_id).facet;
  const associationPending=c.status==='needs_review'||[base.a_material_status||base.material_status,base.b_material_status].includes('needs_revalidation');
  let itemIndex=0,unassignedIndex=0;
  const mappings=(f.a_links||[]).filter(l=>!['withdrawn','superseded'].includes(l.status)).map(l=>{
   const known=base.a_reference.items.some(a=>a.id===l.a_item_id),savedKind=known?c.a_items[itemIndex++]?.kind:c.a_unassigned[unassignedIndex++];
   // Disposition associations have no content-coverage bucket; retain their
   // saved source, facet and link review boundaries without adding coverage.
   return {link:l,kind:savedKind??(associationPending||l.status==='needs_review'||l.version!==base.a_version||(!known&&l.a_item_id!=null)?'needs_review':l.kind)};
  });
  const title=mappings.length?mappings.map(({link:l,kind})=>name(kind||l.kind)+'：'+aTitle(l.a_item_id,l.version,true)).join('；'):aReading(c);
  node(mappings.length?'h4':'p',(f.qualifiers?.object||'关注点 '+(cs.indexOf(c)+1))+' · '+title,a);
  for(const {link:l,kind} of mappings)explain(a,'A关联 · '+name(kind||l.kind)+' / '+name(kind==='needs_review'?'needs_review':l.status),l.scope+' · '+(l.reason||'未说明'));
  const outsidePositions=positions.placements.filter(p=>p.facet_id===c.facet_id&&p.proposed_kind==null&&['outside','stale'].includes(p.region_id));
  (f.outside||[]).filter(l=>!['withdrawn','superseded'].includes(l.status)).forEach((l,i)=>{
   explain(a,'清单外范围 · '+name(outsidePositions[i]?.review_status||(associationPending?'needs_review':l.status)),l.scope);explain(a,'依据',l.reason);
  });
 }
 if(!cs.length)node('p',(base.a_reference.items||[]).length?'尚未标注 A 对应':'尚未导入 A，可先整理 B。',a);
 const actions=node('div',null,center,{class:'focus-actions'});
 if($('attention-editor')){const edit=node('button','修改解释',actions,{type:'button',class:'focus-primary'});
 edit.onclick=()=>document.dispatchEvent(new CustomEvent(cs.length?'attention-edit-facet':'attention-edit-record',{detail:cs.length?(cs.find(c=>c.facet_id===selectedFacet)||cs[0]):{record_id:selectedRecord}}));}
 node('span','已保存修订 '+base.revision,actions,{class:'focus-secondary'});
 node('button','查看原话',actions,{type:'button'}).onclick=()=>showSource(cs[0]);
 const ref=node('details',null,center,{class:'focus-reference'});node('summary','参考方向 A（'+base.a_reference.items.length+' 项）',ref);
 for(const item of base.a_reference.items){node('h4',item.id,ref);node('p',item.text,ref);explain(ref,'位置',item.locator);}explain(ref,'版本',base.a_version);
 sourcePanel.hidden=!sourceOpen;shell.classList.toggle('source-open',sourceOpen);
 if(sourceOpen){
  const close=node('button','关闭来源',sourcePanel,{type:'button'});close.onclick=()=>{sourceOpen=false;focusReading();};
  node('h2','来源查证',sourcePanel);node('p','评语原话',sourcePanel,{class:'focus-secondary'});
  const f=base.details[selectedRecord].facets.find(e=>e.facet.facet_id===selectedFacet)?.facet;
  for(const section of r.sections||[{text:r.text,section_id:r.anchor}]){
   const q=node('blockquote',null,sourcePanel);const ev=f?.evidence?.filter(e=>e.section_id===section.section_id).sort((a,b)=>a.start-b.start)||[];
   const chars=Array.from(section.text||'');let offset=0;
   for(const e of ev){if(e.start<offset)continue;q.append(document.createTextNode(chars.slice(offset,e.start).join('')));node('mark',chars.slice(e.start,e.end).join(''),q);offset=e.end;}
   q.append(document.createTextNode(chars.slice(offset).join('')));explain(sourcePanel,'原话位置',section.section_id);
  }
  node('h3','已选中片段',sourcePanel);evidence(sourcePanel,f?.evidence);explain(sourcePanel,'原分',(r.scores||[]).map(s=>s.label+'：'+s.raw_value).join('；')||'未提供');
  const provenance=node('details',null,sourcePanel);node('summary','来源位置与权限',provenance);explain(provenance,'材料组',paperId(r)??'未知');explain(provenance,'来源',r.source_id);explain(provenance,'可见性',({author_visible:'作者可见',visibility_unknown:'可见范围未知'}[r.visibility]||r.visibility));
 }
 document.querySelectorAll('#view-detail > details[id^="view-record-"]').forEach(d=>{d.hidden=d.id!==anchor(selectedRecord);});
}
const distribution=node('button','关注分布',document.querySelector('header nav'),{type:'button',id:'focus-distribution','aria-expanded':'false'});
const optionHome=document.createComment('distribution disclosure home');$('view-options').before(optionHome);
function distributionMode(open){
 const options=$('view-options');options.open=open;center.hidden=open;shell.classList.toggle('distribution-open',open);
 distribution.setAttribute('aria-expanded',String(open));
 if(open){center.after(options);$('view-a-positions').open=true;}else optionHome.after(options);
}
distribution.onclick=()=>distributionMode(distribution.getAttribute('aria-expanded')!=='true');
document.querySelector('a[href="#focus-shell"]')?.addEventListener('click',()=>distributionMode(false));

function refresh(){
 const v=Object.fromEntries(Object.entries(picks).map(([k,s])=>[k,s.value]));
 const ids=recordOrder.filter(id=>(v.record==='*'||id===v.record)&&(v.paper==='*'||JSON.stringify(paperId(base.details[id].record))===v.paper));
 const cs=base.contributions.filter(c=>ids.includes(c.record_id)&&(v.function==='*'||(c.expression.function||'未说明')===v.function)&&(v.direction==='*'||c.directions.includes(v.direction))&&(v.status==='*'||c.status===v.status)&&(v.boiler==='*'||JSON.stringify(c.expression.boilerplate_candidate??null)===v.boiler));
 const facets=new Set(cs.map(c=>c.facet_id));
 const relations=base.relation_details.filter(r=>r.endpoints.length&&r.endpoints.every(e=>facets.has(e.facet_id)));
 current={ids,cs,relations};
 const aPending=cs.filter(c=>c.a_items.some(a=>a.kind==='needs_review')||c.a_unassigned.includes('needs_review')).length;
 const outsidePending=cs.filter(c=>c.outside.includes('needs_review')).length;
 const pending=[['B解释',cs.filter(c=>c.status==='needs_review').length],['A对应',aPending],['清单外范围',outsidePending]].filter(([,n])=>n);
 $('view-version').textContent='当前范围 '+ids.length+' 条记录（分母）'+(pending.length?' · 待核对：'+pending.map(([t,n])=>t+' '+n+' 项').join('、')+'（可重叠）':'');
 const hits=unique(cs.map(c=>c.record_id)),filtered=Object.values(v).some(value=>value!=='*');$('view-hits').textContent=filtered?'筛选命中 '+hits.length+'/'+ids.length+' 条记录（表达筛选保留分母）':'';
 $('view-summary').replaceChildren();overview();
 node('p','各项允许重叠，父主题/A部分按记录取并集。未核对解释、部分、相关、未定及待核分别保留；待核不合称明确覆盖。数字描述本批表达，不代表群体重要性、论文质量或A权重。未提及不表示不关注。',$('view-summary'));
 const content=cs.filter(c=>c.kind==='content');
 group('主题与父组',Object.entries(base.theme_definitions).map(([id,t])=>[t.label+' · '+t.definition,content.filter(c=>c.theme_ids.includes(id))]));
 for(const [field,title,defs] of [['a_parts','A部分（记录并集）',base.a_reference.parts||[]],['a_items','A条目',base.a_reference.items||[]]]){
 group(title,defs.flatMap(d=>Object.keys(base[field][d.id]).map(kind=>[d.id+' · '+(d.label||d.text)+' · '+name(kind),content.filter(c=>c[field].some(a=>a.id===d.id&&a.kind===kind))])));
 }
 group('无当前条目归属的A关联',Object.keys(base.a_unassigned).map(k=>[name(k),content.filter(c=>c.a_unassigned.includes(k))]));
 group('清单外',unique(base.contributions.flatMap(c=>c.outside)).map(k=>[name(k),content.filter(c=>c.outside.includes(k))]));
 group('判断方向',unique(base.contributions.filter(c=>c.kind==='content').flatMap(c=>c.directions)).map(k=>[k,content.filter(c=>c.directions.includes(k))]));
 group('方面核对状态',unique(base.contributions.filter(c=>c.kind==='content').map(c=>c.status)).map(k=>[name(k),content.filter(c=>c.status===k)]));
 for(const kind of ['content','disposition']){const subset=cs.filter(c=>c.kind===kind);group(name(kind)+'辅助数：'+unique(subset.map(c=>c.opinion_id)).length+'观点 / '+unique(subset.map(c=>c.facet_id)).length+'方面',[[name(kind)+'记录',subset]]);}
 group('关系（单列，不作主题排名）',Object.keys(base.relations).map(type=>[name(type),relations.filter(r=>r.type===type).flatMap(r=>r.endpoints.map(e=>cs.find(c=>c.facet_id===e.facet_id)))]));
 details();focusReading();matrix();graph();
}
function details(){const root=$('view-detail');root.replaceChildren();if(!current.ids.length)node('p','当前筛选没有记录；请调整筛选。',root);else if(!current.cs.length)node('p','尚无可读的B解释。可调整筛选，或打开“查看原话与修改”补录；导入材料不等于完成分析。',root);
 for(const id of current.ids){const d=base.details[id],r=d.record,cs=current.cs.filter(c=>c.record_id===id);const det=node('details',null,root,{id:anchor(id)}),heading=node('summary',null,det);
 node('span',r.anchor||id,heading,{class:'reading-meta'});
 if(!cs.length)node('span','暂无命中解释 · 仍计入分母',heading,{class:'reading-facet'});
 for(const c of cs){const line=node('span',null,heading,{class:'reading-facet'});node('span',readingTitle(facetLabel(c)),line,{class:'reading-title',title:facetLabel(c)});if(c.status!=='confirmed')node('small',' · '+name(c.status),line);node('span','与A：'+aReading(c),line,{class:'reading-a'});}
 const source=node('details',null,det,{class:'record-source'});node('summary','本条完整原话与原分',source);explain(source,'材料组',paperId(r)??'未知');for(const s of r.sections||[{text:r.text,section_id:r.anchor}]){explain(source,'原话位置',s.section_id);node('blockquote',s.text,source);}explain(source,'原分',(r.scores||[]).map(s=>s.label+'：'+s.raw_value).join('；')||'未提供');
 for(const c of cs){const entry=d.facets.find(e=>e.facet.facet_id===c.facet_id),f=entry.facet;const section=node('div',null,det,{id:facetAnchor(c.facet_id)});node('h4',f.interpretation,section);node('button','查看原话并修改',section,{type:'button'}).onclick=()=>document.dispatchEvent(new CustomEvent('attention-edit-facet',{detail:{record_id:id,opinion_id:c.opinion_id,facet_id:c.facet_id}}));evidence(section,f.evidence);
 const rationale=node('details',null,section);node('summary','解释依据与表达方式',rationale);explain(rationale,'完整观点',entry.opinion_interpretation||f.interpretation);explain(rationale,'类型 / 核对',name(c.kind)+' / '+name(c.status));for(const [key,title] of Object.entries({object:'对象',direction:'方向',degree:'程度',negation:'否定',reasons:'理由',conditions:'条件',actions:'动作',examples:'例示',alternatives:'备选'}))explain(rationale,title,f.qualifiers?.[key]);explain(rationale,'表达作用',c.expression.function||'未说明');explain(rationale,'套话候选',c.expression.boilerplate_candidate==null?'未判断':c.expression.boilerplate_candidate?'是候选':'非候选');explain(rationale,'主题',c.theme_ids.map(id=>base.theme_definitions[id]?.label||id));
 const aDetail=node('details',null,section,{class:'facet-a'});node('summary','与A对照的范围和理由',aDetail);for(const a of c.a_items)explain(aDetail,'当前对应',aTitle(a.id,a.version)+' / '+name(a.kind));
 for(const a of f.a_links||[]){explain(aDetail,'保存的对应',aTitle(a.a_item_id,a.version)+' / '+name(a.kind)+' / '+name(a.status));explain(aDetail,'范围',a.scope);explain(aDetail,'依据',a.reason);evidence(aDetail,a.evidence);}
 for(const a of f.outside||[]){explain(aDetail,'清单外范围',a.scope);explain(aDetail,'依据 / 核对',(a.reason||'未说明')+' / '+name(a.status));evidence(aDetail,a.evidence);}
 }}
 if(current.relations.length)node('h3','B关注之间的联系',root);
 for(const r of current.relations){const d=node('details',null,root,{id:relationAnchor(r.relation_id)});node('summary',r.reading||r.scope||name(r.type),d);explain(d,'核对',name(r.status));explain(d,'关系类型',name(r.type));for(const e of r.endpoints){const c=current.cs.find(c=>c.facet_id===e.facet_id),f=base.details[c.record_id].facets.find(f=>f.facet.facet_id===c.facet_id).facet;link(d,(e.role?e.role+'：':'')+f.interpretation,facetAnchor(e.facet_id));node('br',null,d);}for(const [k,t] of [['direction','方向说明'],['scope','作用范围'],['reading','理解'],['ambiguity','歧义与未决']])explain(d,t,r[k]);evidence(d,r.evidence);}
}
let matrixKind='theme';
function matrix(){const root=$('view-matrix');root.hidden=!$('view-matrix-toggle').checked;if(root.hidden)return;root.replaceChildren();node('p','已保存修订 '+base.revision+' · 分母 '+current.ids.length+' · 与上方相同筛选。每格按记录去重；同一记录可落在多个列，列总数不可相加。A按有效关系种类分列，待核不冒称明确。清单外/条目未定独立保留。',root);const l=node('label','矩阵列',root),s=node('select',null,l,{id:'view-matrix-kind'});for(const [v,t] of [['theme','B主题'],['a','A部分与条目']])node('option',t,s,{value:v});s.value=matrixKind;s.onchange=()=>{matrixKind=s.value;matrix();};
 let columns=matrixKind==='theme'?Object.entries(base.theme_definitions).map(([id,t])=>[t.label,c=>c.theme_ids.includes(id)]):['a_parts','a_items'].flatMap(field=>Object.entries(base[field]).flatMap(([id,kinds])=>Object.keys(kinds).map(k=>[(field==='a_parts'?'部分 ':'条目 ')+id+' / '+name(k),c=>c[field].some(a=>a.id===id&&a.kind===k)])));
 columns.push(['清单外',c=>c.outside.length>0],['A条目未定/待核',c=>c.a_unassigned.length>0]);
 node('p','左右滑动或滚动，查看更多主题/A列；键盘聚焦表格后可用方向键滚动。',root,{id:'view-matrix-hint'});
 const wrap=node('div',null,root,{class:'view-scroll',tabindex:'0','aria-label':'矩阵横向滚动'}),table=node('table',null,wrap);node('caption','记录×'+(matrixKind==='theme'?'主题':'A部分/条目')+'；格中数字为本条记录0或1，链接到方面证据',table);const head=node('tr',null,node('thead',null,table));node('th','评语记录',head,{scope:'col'});for(const [title] of columns)node('th',title,head,{scope:'col'});const body=node('tbody',null,table);for(const id of current.ids){const tr=node('tr',null,body);node('th',base.details[id].record.anchor||id,tr,{scope:'row'});for(const [title,test] of columns){const td=node('td',null,tr),matches=current.cs.filter(c=>c.record_id===id&&c.kind==='content'&&test(c));if(matches.length){node('span','1 · ',td);matches.forEach(c=>{const a=link(td,facetLabel(c).slice(0,12),facetAnchor(c.facet_id));a.title=facetLabel(c)+' · '+c.facet_id;node('span',' ',td);});}else node('span','0',td);}}
}
let local='';
function graph(){const root=$('view-graph');root.hidden=!$('view-graph-toggle').checked;if(root.hidden)return;root.replaceChildren();node('p','已保存修订 '+base.revision+' · 分母 '+current.ids.length+' · 全局命中记录 '+(unique(current.cs.map(c=>c.record_id)).map(recordLabel).join('、')||'无')+'。局部图仅展开所选记录及涉及它的关系组端点；选择局部范围不改变统计分母。',root);node('p','节点以文字标明观点、方面或关系组。浅灰观点/蓝色方面/白色关系组只区分对象类型；线宽固定，不表示权重。灰线是方面归属，蓝线是关系端点与角色；均无推定箭头，原方向以说明为准。位置/距离无相似度或因果意义，未知教师身份不造节点。',root);
 const l=node('label','局部图记录',root),s=node('select',null,l,{id:'view-graph-record'});for(const id of current.ids)node('option',base.details[id].record.anchor||id,s,{value:id});if(!current.ids.includes(local))local=current.ids[0]||'';s.value=local;s.onchange=()=>{local=s.value;graph();};
 const localCs=current.cs.filter(c=>c.record_id===local);if(!localCs.length){node('p','当前局部范围没有命中方面。原话仍可在普通明细回查。',root);return;}
 const rs=current.relations.filter(r=>r.endpoints.some(e=>localCs.some(c=>c.facet_id===e.facet_id)));
 const cs=current.cs.filter(c=>c.record_id===local||rs.some(r=>r.endpoints.some(e=>e.facet_id===c.facet_id)));
 node('p','左右滑动或滚动，查看更多方面与关系组；键盘聚焦图形后可用方向键滚动。',root,{id:'view-graph-hint'});
 const wrap=node('div',null,root,{class:'view-scroll',tabindex:'0','aria-label':'局部图横向滚动'}),ns='http://www.w3.org/2000/svg';
 const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 960 '+Math.max(160,cs.length*85,rs.length*110));svg.setAttribute('role','img');svg.setAttribute('aria-label','观点方面与关系组局部图');wrap.append(svg);
 function sn(tag,attrs,parent=svg,text){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;parent.append(e);return e;}
 const geometry={opinionX:0,facetX:310,relationX:740,width:190};
 const positions=new Map(cs.map((c,i)=>[c.facet_id,45+i*85]));const ops=unique(cs.map(c=>c.opinion_id));
 for(const c of cs){sn('line',{x1:geometry.opinionX+geometry.width,y1:45+ops.indexOf(c.opinion_id)*85,x2:geometry.facetX,y2:positions.get(c.facet_id),stroke:'#697d90'});}
 for(const [i,r] of rs.entries())for(const e of r.endpoints){const a=sn('a',{href:'#'+relationAnchor(r.relation_id),'aria-label':'关系端点：'+(e.role||'角色未说明')+' / '+(r.direction||'方向未说明')+' / '+r.scope+'；查看完整证据'});sn('line',{x1:geometry.facetX+geometry.width,y1:positions.get(e.facet_id),x2:geometry.relationX,y2:55+i*110,stroke:'#315879'},a);sn('title',{},a,(e.role||'角色未说明')+' / '+(r.direction||'方向未说明')+' / '+r.scope);}
 function box(x,y,text,href,fill){const a=sn('a',{href:'#'+href});sn('rect',{x,y:y-23,width:geometry.width,height:48,rx:4,fill,stroke:'#697d90'},a);sn('title',{},a,text);sn('text',{x:x+8,y:y+4},a,text.length>12?text.slice(0,11)+'…':text);}
 ops.forEach((id,i)=>box(geometry.opinionX,45+i*85,'观点 '+(base.details[cs.find(c=>c.opinion_id===id).record_id].facets.find(e=>e.opinion_id===id)?.opinion_interpretation||id),anchor(cs.find(c=>c.opinion_id===id).record_id),'#eef1f5'));
 cs.forEach(c=>box(geometry.facetX,positions.get(c.facet_id),'方面 '+facetLabel(c),facetAnchor(c.facet_id),'#dce8f1'));
 rs.forEach((r,i)=>box(geometry.relationX,55+i*110,'关系组 '+name(r.type),relationAnchor(r.relation_id),'#ffffff'));
 node('p','图中方面 '+cs.length+' 个；观点 '+ops.length+' 个；关系组 '+rs.length+' 个（均为辅助对象数，非独立记录数）。点击节点或蓝线可回查原话与关系明细。',root);
}
$('view-matrix-toggle').onchange=matrix;$('view-graph-toggle').onchange=graph;
// Native disclosure navigation also works on direct links and browser history.
function reveal(target){
 if(!target)return;
 const record=target.closest('[id^="view-record-"]');
 if(record){const id=Object.keys(base.details).find(id=>anchor(id)===record.id);if(id&&id!==selectedRecord){selectedRecord=id;sourceOpen=false;focusReading();}record.hidden=false;}
 for(let p=target;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
 if(target.id.startsWith('view-facet-'))for(const detail of target.querySelectorAll(':scope > details'))detail.open=true;
 target.setAttribute('tabindex','-1');target.focus({preventScroll:true});target.scrollIntoView({block:'start'});
}
function hashTarget(hash){try{return $(hash.slice(1))||$(decodeURIComponent(hash.slice(1)));}catch{return null;}}
window.AttentionReading={reveal};
document.addEventListener('click',e=>{const href=e.target.closest('a')?.getAttribute('href');if(!href?.startsWith('#'))return;const target=hashTarget(href);if(target)reveal(target);});
window.addEventListener('hashchange',()=>reveal(hashTarget(location.hash)));
refresh();
requestAnimationFrame(()=>reveal(hashTarget(location.hash)));
})();
