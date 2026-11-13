/* Offline saved-result views. A classification comes exclusively from summarize(). */
(() => {
'use strict';
const base=JSON.parse(document.getElementById('attention-summary-data').textContent);
const $=id=>document.getElementById(id);
const labels={withdrawn:'撤回',superseded:'已被替换',working:'工作解释',needs_review:'待核对',confirmed:'已核对分析',explicit:'明确对应',partial:'部分对应',related:'内容相关',undetermined:'暂未定',content:'内容关注',disposition:'流程或总体处置',reason:'理由',conditional_fallback:'条件备用动作',alternative:'备选路径',co_occurrence:'相伴表达'};
Object.assign(labels,{alternative_with_condition:'有条件的备选路径',coexisting_readings:'并存读法',shared_premise:'共同前提',alternative_with_minimum:'有最低动作的备选路径',suggestion_timing:'建议时机',declared_reason_scope:'明示理由范围',listed_ways_not_all_mandatory:'列举路径（非全部必做）',listed_ways_and_explicit_suggestion:'列举路径与明确建议',co_written_scope_unresolved:'共同表述（范围未决）'});
const name=v=>labels[v]||v||'未说明';
const recordLabel=id=>base.details[id]?.record.anchor||id;
const facetLabel=c=>base.details[c.record_id].facets.find(e=>e.facet.facet_id===c.facet_id)?.facet.interpretation||c.facet_id;
const node=(tag,text,parent,attrs={})=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(parent)parent.append(e);return e;};
const unique=xs=>[...new Set(xs)].sort();
const controls=$('view-controls');
const picks={};
function pick(key,title,values){const l=node('label',title,controls),s=node('select',null,l,{id:'view-'+key});node('option','全部',s,{value:'*'});for(const [value,text] of values)node('option',text,s,{value});s.onchange=refresh;picks[key]=s;}
pick('record','记录筛选（改变分母）',Object.entries(base.details).map(([id,d])=>[id,d.record.anchor||id]));
pick('paper','材料筛选（改变分母）',unique(Object.values(base.details).map(d=>JSON.stringify(d.record.locator?.paper_id??null))).map(v=>[v,JSON.parse(v)??'未知材料组']));
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
function explain(parent,title,value){if(value!=null&&value!=='')node('p',title+'：'+(Array.isArray(value)?value.join('；'):value),parent);}
function refresh(){
 const v=Object.fromEntries(Object.entries(picks).map(([k,s])=>[k,s.value]));
 const ids=Object.keys(base.details).filter(id=>(v.record==='*'||id===v.record)&&(v.paper==='*'||JSON.stringify(base.details[id].record.locator?.paper_id??null)===v.paper));
 const cs=base.contributions.filter(c=>ids.includes(c.record_id)&&(v.function==='*'||(c.expression.function||'未说明')===v.function)&&(v.direction==='*'||c.directions.includes(v.direction))&&(v.status==='*'||c.status===v.status)&&(v.boiler==='*'||JSON.stringify(c.expression.boilerplate_candidate??null)===v.boiler));
 const facets=new Set(cs.map(c=>c.facet_id));
 const relations=base.relation_details.filter(r=>r.endpoints.length&&r.endpoints.every(e=>facets.has(e.facet_id)));
 current={ids,cs,relations};
 $('view-version').textContent='已保存修订 '+base.revision+' · A版本 '+(base.a_version||'未导入')+' · 分析约定版本 '+base.rules_version+' · 材料状态 '+(base.material_status||'未说明');
 const hits=unique(cs.map(c=>c.record_id));$('view-hits').textContent='命中 '+hits.length+'/'+ids.length+' · '+(hits.map(recordLabel).join('、')||'无命中记录');
 $('view-summary').replaceChildren();
 node('p','各项允许重叠，父主题/A部分按记录取并集。工作解释、部分、相关、未定及待核分别保留；待核不合称明确覆盖。数字描述本批表达，不代表群体重要性、论文质量或A权重。未提及不表示不关注。',$('view-summary'));
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
 details();matrix();graph();
}
function details(){const root=$('view-detail');root.replaceChildren();node('h3','当前命中明细与原话原分',root);node('p','点击数字、矩阵或图只定位证据，不改变分母。未命中方面不混入当前结果；撤回/替换历史见页末。',root);
 for(const id of current.ids){const d=base.details[id],r=d.record,cs=current.cs.filter(c=>c.record_id===id);const det=node('details',null,root,{id:anchor(id)});node('summary',(r.anchor||id)+' · '+cs.length+'个命中方面',det);explain(det,'材料组',r.locator?.paper_id??'未知');for(const s of r.sections||[{text:r.text,section_id:r.anchor}]){explain(det,'普通分区',s.section_id);node('blockquote',s.text,det);}explain(det,'原分',(r.scores||[]).map(s=>s.label+'：'+s.raw_value).join('；')||'未提供');if(!cs.length)node('p','没有命中方面；该记录仍在分母中。',det);
 for(const c of cs){const entry=d.facets.find(e=>e.facet.facet_id===c.facet_id),f=entry.facet;const section=node('div',null,det,{id:facetAnchor(c.facet_id)});node('h4',f.interpretation,section);explain(section,'观点',entry.opinion_interpretation||c.opinion_id);explain(section,'类型 / 状态',name(c.kind)+' / '+name(c.status));evidence(section,f.evidence);for(const [key,title] of Object.entries({object:'对象',direction:'方向',degree:'程度',negation:'否定',reasons:'理由',conditions:'条件',actions:'动作',examples:'例示',alternatives:'备选'}))explain(section,title,f.qualifiers?.[key]);explain(section,'表达作用',c.expression.function||'未说明');explain(section,'套话候选',c.expression.boilerplate_candidate==null?'未判断':c.expression.boilerplate_candidate?'是候选':'非候选');explain(section,'主题与父组',c.theme_ids.map(id=>base.theme_definitions[id]?.label||id));
 for(const a of c.a_items)explain(section,'当前有效A列',a.id+' / '+name(a.kind));
 for(const a of f.a_links||[]){explain(section,'保存A关联',(a.a_item_id||'条目未定')+' / '+name(a.kind)+' / '+name(a.status)+' / '+a.version);explain(section,'范围',a.scope);explain(section,'依据',a.reason);evidence(section,a.evidence);}
 for(const a of f.outside||[]){explain(section,'清单外范围',a.scope);explain(section,'依据 / 状态',(a.reason||'未说明')+' / '+name(a.status));evidence(section,a.evidence);}
 }}
 node('h3','当前关系角色、方向与范围',root);
 for(const r of current.relations){const d=node('details',null,root,{id:relationAnchor(r.relation_id)});node('summary',name(r.type)+' · '+r.relation_id+' · '+name(r.status),d);for(const e of r.endpoints){const c=current.cs.find(c=>c.facet_id===e.facet_id),f=base.details[c.record_id].facets.find(f=>f.facet.facet_id===c.facet_id).facet;link(d,(e.role||'角色未说明')+'：'+f.interpretation,facetAnchor(e.facet_id));node('br',null,d);}for(const [k,t] of [['direction','原方向说明'],['scope','作用范围'],['reading','工作读法'],['ambiguity','歧义与未决']])explain(d,t,r[k]||'未说明');evidence(d,r.evidence);}
}
let matrixKind='theme';
function matrix(){const root=$('view-matrix');root.hidden=!$('view-matrix-toggle').checked;if(root.hidden)return;root.replaceChildren();node('p','已保存修订 '+base.revision+' · 分母 '+current.ids.length+' · 与上方相同筛选。每格按记录去重；同一记录可落在多个列，列总数不可相加。A按有效关系种类分列，待核不冒称明确。清单外/条目未定独立保留。',root);const l=node('label','矩阵列',root),s=node('select',null,l,{id:'view-matrix-kind'});for(const [v,t] of [['theme','B主题'],['a','A部分与条目']])node('option',t,s,{value:v});s.value=matrixKind;s.onchange=()=>{matrixKind=s.value;matrix();};
 let columns=matrixKind==='theme'?Object.entries(base.theme_definitions).map(([id,t])=>[t.label,c=>c.theme_ids.includes(id)]):['a_parts','a_items'].flatMap(field=>Object.entries(base[field]).flatMap(([id,kinds])=>Object.keys(kinds).map(k=>[(field==='a_parts'?'部分 ':'条目 ')+id+' / '+name(k),c=>c[field].some(a=>a.id===id&&a.kind===k)])));
 columns.push(['清单外',c=>c.outside.length>0],['A条目未定/待核',c=>c.a_unassigned.length>0]);
 const wrap=node('div',null,root,{class:'view-scroll',tabindex:'0','aria-label':'矩阵横向滚动'}),table=node('table',null,wrap);node('caption','记录×'+(matrixKind==='theme'?'主题':'A部分/条目')+'；格中数字为本条记录0或1，链接到方面证据',table);const head=node('tr',null,node('thead',null,table));node('th','评语记录',head,{scope:'col'});for(const [title] of columns)node('th',title,head,{scope:'col'});const body=node('tbody',null,table);for(const id of current.ids){const tr=node('tr',null,body);node('th',base.details[id].record.anchor||id,tr,{scope:'row'});for(const [title,test] of columns){const td=node('td',null,tr),matches=current.cs.filter(c=>c.record_id===id&&c.kind==='content'&&test(c));if(matches.length){node('span','1 · ',td);matches.forEach(c=>{const a=link(td,facetLabel(c).slice(0,12),facetAnchor(c.facet_id));a.title=facetLabel(c)+' · '+c.facet_id;node('span',' ',td);});}else node('span','0',td);}}
}
let local='';
function graph(){const root=$('view-graph');root.hidden=!$('view-graph-toggle').checked;if(root.hidden)return;root.replaceChildren();node('p','已保存修订 '+base.revision+' · 分母 '+current.ids.length+' · 全局命中记录 '+(unique(current.cs.map(c=>c.record_id)).map(recordLabel).join('、')||'无')+'。局部图仅展开所选记录及涉及它的关系组端点；选择局部范围不改变统计分母。',root);node('p','节点以文字标明观点、方面或关系组。浅灰观点/蓝色方面/白色关系组只区分对象类型；线宽固定，不表示权重。灰线是方面归属，蓝线是关系端点与角色；均无推定箭头，原方向以说明为准。位置/距离无相似度或因果意义，未知教师身份不造节点。',root);
 const l=node('label','局部图记录',root),s=node('select',null,l,{id:'view-graph-record'});for(const id of current.ids)node('option',base.details[id].record.anchor||id,s,{value:id});if(!current.ids.includes(local))local=current.ids[0]||'';s.value=local;s.onchange=()=>{local=s.value;graph();};
 const localCs=current.cs.filter(c=>c.record_id===local);if(!localCs.length){node('p','当前局部范围没有命中方面。原话仍可在普通明细回查。',root);return;}
 const rs=current.relations.filter(r=>r.endpoints.some(e=>localCs.some(c=>c.facet_id===e.facet_id)));
 const cs=current.cs.filter(c=>c.record_id===local||rs.some(r=>r.endpoints.some(e=>e.facet_id===c.facet_id)));
 const wrap=node('div',null,root,{class:'view-scroll',tabindex:'0','aria-label':'局部图横向滚动'}),ns='http://www.w3.org/2000/svg';
 const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 960 '+Math.max(160,cs.length*85,rs.length*110));svg.setAttribute('role','img');svg.setAttribute('aria-label','观点方面与关系组局部图');wrap.append(svg);
 function sn(tag,attrs,parent=svg,text){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;parent.append(e);return e;}
 const positions=new Map(cs.map((c,i)=>[c.facet_id,45+i*85]));const ops=unique(cs.map(c=>c.opinion_id));
 for(const c of cs){sn('line',{x1:190,y1:45+ops.indexOf(c.opinion_id)*85,x2:310,y2:positions.get(c.facet_id),stroke:'#697d90'});}
 for(const [i,r] of rs.entries())for(const e of r.endpoints){const a=sn('a',{href:'#'+relationAnchor(r.relation_id),'aria-label':'关系端点：'+(e.role||'角色未说明')+' / '+(r.direction||'方向未说明')+' / '+r.scope+'；查看完整证据'});sn('line',{x1:560,y1:positions.get(e.facet_id),x2:740,y2:55+i*110,stroke:'#315879'},a);sn('title',{},a,(e.role||'角色未说明')+' / '+(r.direction||'方向未说明')+' / '+r.scope);}
 function box(x,y,text,href,fill){const a=sn('a',{href:'#'+href});sn('rect',{x,y:y-23,width:190,height:48,rx:4,fill,stroke:'#697d90'},a);sn('title',{},a,text);sn('text',{x:x+8,y:y+4},a,text.length>15?text.slice(0,14)+'…':text);}
 ops.forEach((id,i)=>box(0,45+i*85,'观点 '+(base.details[cs.find(c=>c.opinion_id===id).record_id].facets.find(e=>e.opinion_id===id)?.opinion_interpretation||id),anchor(cs.find(c=>c.opinion_id===id).record_id),'#eef1f5'));
 cs.forEach(c=>box(310,positions.get(c.facet_id),'方面 '+facetLabel(c),facetAnchor(c.facet_id),'#dce8f1'));
 rs.forEach((r,i)=>box(740,55+i*110,'关系组 '+name(r.type),relationAnchor(r.relation_id),'#ffffff'));
 node('p','图中方面 '+cs.length+' 个；观点 '+ops.length+' 个；关系组 '+rs.length+' 个（均为辅助对象数，非独立记录数）。点击节点或蓝线可回查原话与关系明细。',root);
}
$('view-matrix-toggle').onchange=matrix;$('view-graph-toggle').onchange=graph;
document.addEventListener('click',e=>{const a=e.target.closest('a');if(!a?.getAttribute('href')?.startsWith('#view-'))return;const id=a.getAttribute('href').slice(1),target=$(id);if(!target)return;for(let p=target;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;target.setAttribute('tabindex','-1');target.focus();});
refresh();
})();
