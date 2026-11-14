/* Position geometry is navigation, never a semantic distance or coverage score. */
(() => {
'use strict';
const base=JSON.parse(document.getElementById('attention-position-data').textContent);
const root=document.getElementById('view-positions');
const make=(tag,text,parent,attrs={})=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);parent?.append(e);return e;};
const uniq=xs=>[...new Set(xs)];
make('style',`#candidate-position-regions .candidate-region-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem}@media(max-width:650px){#candidate-position-regions .candidate-region-grid{grid-template-columns:1fr}}`,document.head);
const statuses={needs_review:'待核',working:'工作解释',confirmed:'已核对'};
const kinds={explicit:'明确对应',partial:'部分对应',related:'内容相关',undetermined:'暂未定'};
let selected='',offset=0,lastSelection={recordIds:[],facetIds:[]},overlay=null;
make('style',`#view-positions{margin:1.6rem 0}#attention-views #view-positions svg{min-width:0;width:100%;display:block}#view-positions svg text{font:14px system-ui;fill:#17212e}#view-positions svg a:hover ellipse{fill:#e0eaf1}#view-positions svg a:focus-visible ellipse{stroke:#17212e;stroke-width:3}#view-positions .position-bands{display:flex;flex-wrap:wrap;gap:.5rem}#view-positions .position-bands button{flex:1 1 12rem;text-align:left}#position-drill{border-top:1px solid #c8d0da;margin-top:1rem}#position-drill li{margin:1rem 0}#position-drill small{display:block}#view-positions .position-pending{border:1px dashed #697d90}#view-positions .position-caption{max-width:72ch}`,document.head);
function metric(ps,N){return uniq(ps.map(p=>p.record_id)).length+'/'+N+' 条记录 · '+uniq(ps.map(p=>p.facet_id)).length+' 个方面';}
function render(selection=lastSelection){
 lastSelection=selection;const ids=new Set(selection.recordIds),facets=new Set(selection.facetIds);
 const ps=base.placements.filter(p=>ids.has(p.record_id)&&facets.has(p.facet_id));
 root.replaceChildren();make('h3','B关注位置',root);
 make('p','已保存修订 '+base.revision+' · A版本 '+(base.a_version||'未导入')+' · '+metric(ps,ids.size),root);
 make('p','蓝色区域按当批A条目组织；B标签表示内容方面，可同时出现在多个区域。区域允许重叠且不穷尽，位置、面积、距离均无权重或评分意义。虚线标签是待核建议，不能算已确认覆盖。方向与表达性质请回查明细。',root,{class:'position-caption'});
 const items=base.regions.filter(r=>r.kind==='item');
 const partIds=uniq(items.map(r=>r.part_id));
 for(const part of partIds){
 const rs=items.filter(r=>r.part_id===part);make('h4','A部分 · '+rs[0].part_label+' · '+metric(ps.filter(p=>rs.some(r=>r.id===p.region_id)),ids.size),root);
 // Limit the overview to four regions per sheet, keeping arbitrary A readable.
 for(let start=0;start<rs.length;start+=4){
 const columns=window.innerWidth<650?1:2,ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 '+(columns*410)+' '+(Math.ceil(Math.min(4,rs.length-start)/columns)*230));svg.setAttribute('role','group');svg.setAttribute('aria-label','A参考区域与B位置');root.append(svg);
 const sn=(tag,attrs,parent,text)=>{const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;parent.append(e);return e;};
 rs.slice(start,start+4).forEach((r,i)=>{const x=12+(i%columns)*404,y=8+Math.floor(i/columns)*230,matches=ps.filter(p=>p.region_id===r.id),pending=matches.filter(p=>p.review_status==='needs_review');
 const a=sn('a',{href:'#position-drill','data-position-region':r.id,'aria-label':r.item_id+' '+r.label+'；'+metric(matches,ids.size)},svg);
 sn('ellipse',{cx:x+194,cy:y+109,rx:192,ry:105,fill:'#edf3f7',stroke:'#697d90'},a);
 sn('title',{},a,r.item_id+' · '+r.label+'；'+metric(matches,ids.size));
 sn('text',{x:x+30,y:y+42},a,r.item_id+' · '+r.label.slice(0,18)+(r.label.length>18?'…':''));
 sn('text',{x:x+30,y:y+66},a,metric(matches,ids.size));
 sn('text',{x:x+30,y:y+89},a,'待核 '+uniq(pending.map(p=>p.record_id)).length+' 条记录');
 uniq(matches.map(p=>p.facet_id)).slice(0,3).forEach((fid,j)=>{const p=matches.find(p=>p.facet_id===fid),isPending=p.review_status==='needs_review';
 const token=sn('a',{href:'#view-facet-'+encodeURIComponent(fid),'aria-label':p.label+'；'+(isPending?'待核建议':'保存解释')+'；查看原话'},svg);
 sn('title',{},token,p.label);
 sn('rect',{x:x+54,y:y+94+j*26,width:280,height:25,rx:4,fill:'#fff',stroke:'#315879',...(isPending?{'stroke-dasharray':'4 3'}:{})},token);
 sn('text',{x:x+60,y:y+112+j*26},token,(isPending?'待核 · ':'')+p.label.slice(0,isPending?14:18));});
 if(uniq(matches.map(p=>p.facet_id)).length>3)sn('text',{x:x+30,y:y+204},a,'点击展开全部方面');
 a.onclick=e=>{e.preventDefault();selected=r.id;offset=0;drill(ps,ids.size);document.getElementById('position-drill').scrollIntoView({block:'center'});};
 });}
 }
 const bands=make('div',null,root,{class:'position-bands'});
 for(const r of base.regions.filter(r=>r.kind!=='item')){const matches=ps.filter(p=>p.region_id===r.id);if(!matches.length&&r.id!=='pending'&&r.id!=='outside')continue;
 const b=make('button',r.label+' · '+metric(matches,ids.size),bands,{type:'button','data-position-region':r.id});b.onclick=()=>{selected=r.id;offset=0;drill(ps,ids.size);};}
 if(overlay)renderOverlay(ids,selection.expressionFilters||{});
 if(!selected||!base.regions.some(r=>r.id===selected))selected=items[0]?.id||'absent';
 make('div',null,root,{id:'position-drill','aria-live':'polite'});drill(ps,ids.size);
}
function renderOverlay(ids,v){
 const o=make('section',null,root,{id:'candidate-position-overlay'});
 make('h3','候选建议位置',o);
 make('p',(overlay.accepted_revision!=null?'历史候选（已在修订 '+overlay.accepted_revision+' 接收，以下是生成时待核读法）':'候选预览（未接收、全部待核）')+'：'+overlay.label+'。独立于保存结果及上述统计。布局、距离与面积不表示对应强度。',o);
 if(overlay.validity==='needs_revalidation')make('p','输入或保存修订已变化。位置仅供历史回查；未接收的候选须重新生成。',o);
 const matches=p=>(!p.record_id||ids.has(p.record_id))&&(!v.function||v.function==='*'||(p.expression?.function||'未说明')===v.function)&&(!v.direction||v.direction==='*'||p.directions?.includes(v.direction))&&(!v.status||v.status==='*'||v.status==='needs_review')&&(!v.boiler||v.boiler==='*'||JSON.stringify(p.expression?.boilerplate_candidate??null)===v.boiler);
 const ps=overlay.placements.filter(matches);
 for(const p of overlay.placements){const d=document.getElementById(p.detail_id);if(d)d.hidden=!matches(p);}
 make('p','候选命中 '+metric(ps,ids.size)+'；分母与上方记录/材料筛选相同，表达筛选保留分母。各区域记录去重，不可相加。',o);
 const ns='http://www.w3.org/2000/svg',sn=(tag,attrs,parent,text)=>{const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;parent.append(e);return e;};
 const drill=make('div',null,o,{id:'candidate-position-drill','aria-live':'polite'});
 function detail(r,start=0){
  drill.replaceChildren();const entries=ps.filter(p=>p.region_id===r.id),fids=uniq(entries.map(p=>p.facet_id||p.label));
  make('h4',r.label+' · 候选待核',drill);make('p',metric(entries,ids.size),drill);
  for(const fid of fids.slice(start,start+20)){const es=entries.filter(p=>(p.facet_id||p.label)===fid),p=es[0],item=make('div',null,drill);
   if(p.detail_id)make('a',p.label+' · 逐字证据与限定',item,{href:'#'+p.detail_id});else make('p',p.label,item);
   for(const e of es){make('p','待核 · '+(kinds[e.proposed_kind]||'位置说明')+' · '+(e.scope||'')+' · '+(e.reason||''),item);for(const q of e.evidence||[])make('blockquote',q.quote,item);}
  }
  make('p','显示 '+(fids.length?start+1:0)+'–'+Math.min(start+20,fids.length)+' / '+fids.length+' 个候选方面。接收后在普通关注页核对、纠正并保存。',drill);
  for(const[label,step]of [['上一页',-20],['下一页',20]]){const b=make('button',label,drill,{type:'button'});b.disabled=start+step<0||start+step>=fids.length;b.onclick=()=>detail(r,start+step);}
 }
 const graph=make('div',null,o,{id:'candidate-position-regions'}),groups=new Map();o.append(drill);
 for(const r of base.regions){const entries=ps.filter(p=>p.region_id===r.id);if(!entries.length)continue;
  const group=r.kind==='item'?'part:'+r.part_id:'other';if(!groups.has(group)){make('h4',r.kind==='item'?'A部分 · '+r.part_label:'其他位置',graph);groups.set(group,make('div',null,graph,{class:'candidate-region-grid'}));}
  const svg=sn('svg',{viewBox:'0 0 410 230',role:'group','aria-label':'候选待核区域 '+r.label},groups.get(group));
  const a=sn('a',{href:'#candidate-position-drill','data-candidate-region':r.id,'aria-label':r.label+'；候选待核；'+metric(entries,ids.size)},svg);
  sn('ellipse',{cx:205,cy:112,rx:194,ry:105,fill:'#f6f1e5',stroke:'#695833','stroke-dasharray':'5 4'},a);
  sn('title',{},a,r.label);sn('text',{x:40,y:42},a,(r.item_id?r.item_id+' · ':'')+r.label.slice(0,18));
  sn('text',{x:40,y:68},a,'候选待核 · '+metric(entries,ids.size));
  uniq(entries.map(p=>p.facet_id||p.label)).slice(0,3).forEach((fid,j)=>{const p=entries.find(p=>(p.facet_id||p.label)===fid),token=sn('a',{href:p.detail_id?'#'+p.detail_id:'#candidate-position-drill','aria-label':'候选待核 '+p.label},svg);sn('rect',{x:50,y:85+j*33,width:310,height:28,rx:4,fill:'#fff',stroke:'#695833','stroke-dasharray':'4 3'},token);sn('title',{},token,p.label);sn('text',{x:60,y:104+j*33},token,p.label.slice(0,20));if(!p.detail_id)token.onclick=e=>{e.preventDefault();detail(r);};});
  sn('text',{x:50,y:204},a,'展开全部候选与对应理由');a.onclick=e=>{e.preventDefault();detail(r);drill.scrollIntoView({block:'center'});};
 }
 if(!ps.length)make('p','当前筛选没有候选位置；请调整筛选或查看未完成范围。',graph);
 if(ps.length)detail(base.regions.find(r=>r.id===ps[0].region_id));
}
function drill(ps,N){const d=document.getElementById('position-drill');d.replaceChildren();const r=base.regions.find(r=>r.id===selected),matches=ps.filter(p=>p.region_id===selected),groups=uniq(matches.map(p=>p.facet_id));
 make('h4',(r?.item_id?r.item_id+' · ':'')+(r?.label||'位置明细'),d);make('p',metric(matches,N)+'；各区域不可相加。同方面在此仅列一次，关联范围逐条保留。',d);
 if(offset>=groups.length)offset=0;
 const ul=make('ul',null,d);
 for(const fid of groups.slice(offset,offset+20)){const entries=matches.filter(p=>p.facet_id===fid),p=entries[0],li=make('li',null,ul);
 make('a',p.label,li,{href:'#view-facet-'+encodeURIComponent(fid)});
 make('small','记录 '+p.record_id+' · 方面 '+fid+' · 核对状态 '+(statuses[p.facet_status]||p.facet_status),li);
 for(const e of entries)make('p',(statuses[e.review_status]||e.review_status)+' · '+(kinds[e.proposed_kind]||'位置说明')+' · '+e.scope+' · '+e.reason,li);
 }
 if(!groups.length)make('p','当前筛选无命中；未提及不表示不关注。',d);
 make('p','显示 '+(groups.length?offset+1:0)+'–'+Math.min(offset+20,groups.length)+' / '+groups.length+' 个方面。点击方面查看逐字证据、限定、关联理由与原话编辑入口。',d);
 for(const [label,delta]of [['上一页',-20],['下一页',20]]){const b=make('button',label,d,{type:'button'});b.disabled=offset+delta<0||offset+delta>=groups.length;b.onclick=()=>{offset+=delta;drill(ps,N);};}
}
// C3 passes an independent display-only overlay, bound to this exact saved input.
function setOverlay(value){if(value&&(value.analysis_id!==base.analysis_id||value.base_revision!==base.revision||value.a_version!==base.a_version))throw Error('候选预览与保存输入不匹配');overlay=value?JSON.parse(JSON.stringify(value)):null;
 if(overlay)for(const[id,values]of [['view-function',overlay.placements.map(p=>p.expression?.function||'未说明')],['view-direction',overlay.placements.flatMap(p=>p.directions||[])],['view-status',['needs_review']]]){const select=document.getElementById(id);if(select)for(const value of uniq(values))if(![...select.options].some(o=>o.value===value))make('option',value==='needs_review'?'待核':value,select,{value});}
 render();}
window.addEventListener('resize',()=>render());
window.AttentionPositions=Object.freeze({render,setOverlay});
})();
