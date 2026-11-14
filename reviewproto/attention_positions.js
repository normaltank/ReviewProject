/* Position geometry is navigation, never a semantic distance or coverage score. */
(() => {
'use strict';
const base=JSON.parse(document.getElementById('attention-position-data').textContent);
const root=document.getElementById('view-positions');
const make=(tag,text,parent,attrs={})=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);parent?.append(e);return e;};
const uniq=xs=>[...new Set(xs)];
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
 sn('rect',{x:x+30,y:y+100+j*28,width:320,height:25,rx:4,fill:'#fff',stroke:'#315879',...(isPending?{'stroke-dasharray':'4 3'}:{})},a);
 sn('text',{x:x+38,y:y+118+j*28},a,(isPending?'待核 · ':'')+p.label.slice(0,isPending?16:20));});
 if(uniq(matches.map(p=>p.facet_id)).length>3)sn('text',{x:x+30,y:y+204},a,'点击展开全部方面');
 a.onclick=e=>{e.preventDefault();selected=r.id;offset=0;drill(ps,ids.size);document.getElementById('position-drill').scrollIntoView({block:'center'});};
 });}
 }
 const bands=make('div',null,root,{class:'position-bands'});
 for(const r of base.regions.filter(r=>r.kind!=='item')){const matches=ps.filter(p=>p.region_id===r.id);if(!matches.length&&r.id!=='pending'&&r.id!=='outside')continue;
 const b=make('button',r.label+' · '+metric(matches,ids.size),bands,{type:'button','data-position-region':r.id});b.onclick=()=>{selected=r.id;offset=0;drill(ps,ids.size);};}
 if(overlay){make('p','候选预览（未接收、全部待核）：'+overlay.label+'。独立于保存结果及上述统计。',root);make('p',overlay.placements.map(p=>p.label+' → '+p.region_id+'（待核）').join('；'),root);}
 if(!selected||!base.regions.some(r=>r.id===selected))selected=items[0]?.id||'absent';
 make('div',null,root,{id:'position-drill','aria-live':'polite'});drill(ps,ids.size);
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
function setOverlay(value){if(value&&(value.analysis_id!==base.analysis_id||value.base_revision!==base.revision||value.a_version!==base.a_version))throw Error('候选预览与保存输入不匹配');overlay=value?JSON.parse(JSON.stringify(value)):null;render();}
window.addEventListener('resize',()=>render());
window.AttentionPositions=Object.freeze({render,setOverlay});
})();
