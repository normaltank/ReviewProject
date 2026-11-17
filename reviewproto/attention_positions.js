/* Position geometry is navigation, never a semantic distance or coverage score. */
(() => {
'use strict';
const base=JSON.parse(document.getElementById('attention-position-data').textContent);
const root=document.getElementById('view-positions');
const make=(tag,text,parent,attrs={})=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);parent?.append(e);return e;};
const uniq=xs=>[...new Set(xs)];
make('style',`#candidate-position-regions .candidate-region-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem}@media(max-width:650px){#candidate-position-regions .candidate-region-grid{grid-template-columns:1fr}}`,document.head);
const statuses={needs_review:'待核',working:'未核对解释',confirmed:'已核对'};
const kinds={explicit:'明确对应',partial:'部分对应',related:'内容相关',undetermined:'暂未定'};
let lastSelection={recordIds:[],facetIds:[]},overlay=null;


function metric(ps,N){return uniq(ps.map(p=>p.record_id)).length+'/'+N+' 条记录 · '+uniq(ps.map(p=>p.facet_id)).length+' 个方面';}
function render(selection=lastSelection){
 lastSelection=selection;
 window.AttentionMap.render(selection,root);
 if(overlay)renderOverlay(new Set(selection.recordIds),selection.expressionFilters||{});
}
function renderOverlay(ids,v){
 document.getElementById('candidate-position-overlay')?.remove();
 const o=make('section',null,document.getElementById('candidate-visualization')||root,{id:'candidate-position-overlay'});
 make('h3','候选建议位置',o);
 make('p',(overlay.accepted_revision!=null?'历史候选（已在修订 '+overlay.accepted_revision+' 保存，以下是生成时待核读法）':'候选预览（尚未保存，全部待核）')+'。候选单独展示，不进入已保存结果的统计。布局、距离与面积不表示对应强度。',o);
 if(overlay.validity==='needs_revalidation')make('p','输入或保存修订已变化。位置仅供历史回查；尚未保存的候选须重新生成。',o);
 const matches=p=>(!p.record_id||ids.has(p.record_id))&&(!v.function||v.function==='*'||(p.expression?.function||'未说明')===v.function)&&(!v.direction||v.direction==='*'||p.directions?.includes(v.direction))&&(!v.status||v.status==='*'||v.status==='needs_review')&&(!v.boiler||v.boiler==='*'||JSON.stringify(p.expression?.boilerplate_candidate??null)===v.boiler);
 const ps=overlay.placements.filter(matches);
 for(const p of overlay.placements){const d=document.getElementById(p.detail_id);if(d)d.hidden=!matches(p);}
 make('p','候选命中 '+metric(ps,ids.size)+'；记录/材料筛选改变分母，表达筛选保留分母。各区域记录去重，不可相加。',o);
 const ns='http://www.w3.org/2000/svg',sn=(tag,attrs,parent,text)=>{const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;parent.append(e);return e;};
 const drill=make('div',null,o,{id:'candidate-position-drill','aria-live':'polite'});
 function detail(r,start=0){
  drill.replaceChildren();const entries=ps.filter(p=>p.region_id===r.id),fids=uniq(entries.map(p=>p.facet_id||p.label));
  make('h4',r.label+' · 候选待核',drill);make('p',metric(entries,ids.size),drill);
  for(const fid of fids.slice(start,start+20)){const es=entries.filter(p=>(p.facet_id||p.label)===fid),p=es[0],item=make('div',null,drill);
   if(p.detail_id)make('a',p.label+' · 逐字证据与限定',item,{href:'#'+p.detail_id});else make('p',p.label,item);
   for(const e of es){make('p','待核 · '+(kinds[e.proposed_kind]||'位置说明')+' · '+(e.scope||'')+' · '+(e.reason||''),item);for(const q of e.evidence||[])make('blockquote',q.quote,item);}
  }
  make('p','显示 '+(fids.length?start+1:0)+'–'+Math.min(start+20,fids.length)+' / '+fids.length+' 个候选方面。保存后在分析页核对和修改。',drill);
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
// C3 passes an independent display-only overlay, bound to this exact saved input.
function setOverlay(value){if(value&&(value.analysis_id!==base.analysis_id||value.base_revision!==base.revision||value.a_version!==base.a_version))throw Error('候选预览与保存输入不匹配');overlay=value?JSON.parse(JSON.stringify(value)):null;
 if(overlay)for(const[id,values]of [['view-function',overlay.placements.map(p=>p.expression?.function||'未说明')],['view-direction',overlay.placements.flatMap(p=>p.directions||[])],['view-status',['needs_review']]]){const select=document.getElementById(id);if(select)for(const value of uniq(values))if(![...select.options].some(o=>o.value===value))make('option',value==='needs_review'?'待核':value,select,{value});}
 render();}
window.addEventListener('resize',()=>render());
window.AttentionPositions=Object.freeze({render,setOverlay});
})();
