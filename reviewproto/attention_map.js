/* The map is a projection of the saved contribution and effective-position indexes. */
(() => {
'use strict';
const summary=JSON.parse(document.getElementById('attention-summary-data').textContent);
const positions=JSON.parse(document.getElementById('attention-position-data').textContent);
const ns='http://www.w3.org/2000/svg', unique=xs=>[...new Set(xs)];
const names={explicit:'明确对应',partial:'部分对应',related:'内容相关',undetermined:'暂未定',needs_review:'待核对',working:'未核对',confirmed:'已核对分析'};
const special={outside:'本版A未明示',pending:'对应未定 / 尚未判断',stale:'旧A或来源失效 · 待重新核对',absent:'B关注 · 尚未导入A',disposition:'总体或流程处置 · 单列'};
let showA=true, selection, groups=[], focusedTheme='*', focusedPart='*', mapRoot;
const html=(tag,text,parent,attrs={})=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent?.append(n);return n;};
const svg=(tag,attrs,parent,text)=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;parent?.append(n);return n;};
const facet=c=>summary.details[c.record_id].facets.find(e=>e.facet.facet_id===c.facet_id)?.facet;
const words=id=>(summary.details[id].record.sections||[{text:summary.details[id].record.text}]).map(s=>s.text||'').join(' ');
const short=(s,n=30)=>Array.from(s||'').slice(0,n).join('')+(Array.from(s||'').length>n?'…':'');
function ancestors(id,seen=new Set()){for(const p of summary.theme_definitions[id]?.parent_ids||[])if(!seen.has(p)){seen.add(p);ancestors(p,seen);}return seen;}
function themes(c){
 if(c.kind!=='content')return ['@disposition'];
 const direct=unique((facet(c)?.themes||[]).filter(t=>!['withdrawn','superseded'].includes(t.status)&&c.theme_ids.includes(t.theme_id)).map(t=>t.theme_id));
 return direct.filter(id=>!direct.some(other=>other!==id&&ancestors(other).has(id)));
}
function label(id){return id==='@unthemed'?'未归主题内容':id==='@disposition'?'总体或流程处置':id==='@unprocessed'?'未处理记录':summary.theme_definitions[id]?.label||id;}
function state(p){
 if(p.region_id==='stale')return '来源或A版本失效 · 待核对';
 if(p.region_id==='absent')return '尚未导入A';
 if(p.region_id==='disposition')return '总体或流程处置';
 if(p.region_id==='pending')return p.proposed_kind==='undetermined'?'暂未定 · '+(names[p.review_status]||p.review_status):p.reason?.startsWith('尚无')?'尚未判断A对应':names[p.review_status]||'待核对';
 return (p.region_id==='outside'?'本版A未明示':names[p.proposed_kind]||'位置说明')+' · '+(names[p.review_status]||p.review_status);
}
function model(value){
 const ids=new Set(value.recordIds), fids=new Set(value.facetIds), cs=summary.contributions.filter(c=>ids.has(c.record_id)&&fids.has(c.facet_id));
 const ps=positions.placements.filter(p=>ids.has(p.record_id)&&fids.has(p.facet_id));
 const rows=new Map();
 function add(region,theme,rid,c,ps){const key=JSON.stringify([region,theme]);if(!rows.has(key))rows.set(key,{region,theme,records:new Map()});const records=rows.get(key).records;if(!records.has(rid))records.set(rid,{record_id:rid,facets:[],placements:[]});const r=records.get(rid);if(c&&!r.facets.includes(c.facet_id))r.facets.push(c.facet_id);r.placements.push(...ps);}
 for(const c of cs){const ts=themes(c), tid=ts.length?ts:['@unthemed'], placements=ps.filter(p=>p.facet_id===c.facet_id);
  for(const t of tid)if(showA){for(const region of unique(placements.map(p=>p.region_id)))add(region,t,c.record_id,c,placements.filter(p=>p.region_id===region));}else add(c.kind==='content'?'b':'disposition',t,c.record_id,c,placements);
 }
 // Processing state uses the complete saved index, not the expression-filtered hits.
 for(const rid of ids)if(!summary.contributions.some(c=>c.record_id===rid))add('unprocessed','@unprocessed',rid,null,[]);
 const ordered=[];
 if(showA){
  const regions=positions.regions.filter(r=>r.kind==='item');
  const partIds=unique([...(summary.a_reference.parts||[]).map(p=>p.id),...regions.map(r=>r.part_id)]);
  for(const id of partIds){const partRegions=regions.filter(r=>r.part_id===id);if(!partRegions.length){const p=summary.a_reference.parts.find(p=>p.id===id);ordered.push({id:'empty-part:'+id,label:p.label+' · 尚无条目',part:p.label,part_id:id,kind:'item',rows:[],empty:true});}
   for(const region of partRegions)ordered.push({id:region.id,label:region.label,part:region.part_label,part_id:region.part_id,kind:'item',rows:[...rows.values()].filter(r=>r.region===region.id)});
  }
 }
 for(const region of ['b','outside','pending','stale','absent','disposition','unprocessed']){const matches=[...rows.values()].filter(r=>r.region===region);if(matches.length)ordered.push({id:region,label:region==='b'?'B关注主题':region==='unprocessed'?'未处理 · 可查看原话':special[region],kind:region,rows:matches});}
 return {groups:ordered,cs,ps};
}
function lines(text,limit){const chars=Array.from(text||''),result=[];for(let i=0;i<chars.length;i+=limit)result.push(chars.slice(i,i+limit).join(''));return result.length?result:[''];}
function fullIndex(width, exporting=false){
 const narrow=width<620, pad=22, gap=26, hasA=groups.some(g=>g.kind==='item');
 const leftWidth=hasA&&!narrow?Math.round(width*.62):width;
 const rightWidth=hasA&&!narrow?width-leftWidth-gap:width;
 let ly=exporting?112:28,ry=ly,part;
 const s=svg('svg',{xmlns:ns,width,role:'img','aria-label':'B主题与记录分布 · 分母 '+selection.recordIds.length,'font-family':'Microsoft YaHei UI, Microsoft YaHei, sans-serif','font-size':14});
 svg('rect',{width:'100%',height:'100%',fill:'#17191a'},s);
 svg('title',{},s,'B关注分布 · 当前筛选 · 保存修订 '+summary.revision);
 if(exporting)svg('text',{x:pad,y:28,fill:'#e4e7e8','font-size':18},s,'B关注分布');
 const filters=Object.entries(selection.expressionFilters||{}).filter(([k,v])=>v!=='*').map(([k,v])=>({record:'评语',paper:'材料',function:'表达作用',direction:'方向',status:'核对状态',boiler:'套话候选'}[k])+': '+(k==='record'?short(words(v),22):names[v]||v));
 const meta=['当前筛选 · 分母 '+selection.recordIds.length+' 条评语记录 · 命中 '+unique(groups.flatMap(g=>g.rows.filter(r=>r.theme!=='@unprocessed').flatMap(r=>[...r.records.keys()]))).length+' 条',
  'A版本 '+(summary.a_version||'未导入')+' · 保存修订 '+summary.revision+' · '+(hasA?'显示A参照':'B主题视图'),
  '单位：每个等大点为本主题/位置的一条记录；同源联动，跨组不可相加'];
 if(exporting)meta.forEach((t,i)=>svg('text',{x:pad,y:50+i*19,fill:'#b0b7b9'},s,t));

 for(const g of groups){const isA=g.kind==='item';if(narrow&&!isA&&ly>ry)ry=ly+gap;
  let x=isA||!hasA||narrow?0:leftWidth+gap,w=isA||!hasA||narrow?leftWidth:rightWidth;
  if(narrow)w=width;
  let y=isA?ly:hasA?ry:ly;
  if(isA&&g.part_id!==part){for(const line of lines('A · '+g.part,Math.floor((w-pad*2)/15))){svg('text',{x:pad,y:y+10,fill:'#b0b7b9','font-size':15},s,line);y+=21;}y+=9;part=g.part_id;}
  const titleLines=lines(g.label,Math.max(8,Math.floor((w-pad*2)/14)));
  const bodyStart=y+titleLines.length*21+18;
  const perRow=Math.max(1,Math.floor((w-pad*2)/32));
  let bottom=bodyStart;
  const selected=selection.selectedRecordId;
  const region=svg('g',{'data-position-region':g.id,...(g.rows.some(r=>r.records.has(selected))?{'aria-current':'true'}:{})},s);
  titleLines.forEach((text,i)=>svg('text',{x:x+pad,y:y+18+i*21,fill:'#b0b7b9'},region,text));
  if(!g.rows.length){svg('text',{x:x+pad,y:bodyStart+15,fill:'#b0b7b9'},region,g.empty?'本部分尚未录入A条目':'尚无当前采用的对应 · 0/'+selection.recordIds.length);bottom+=44;}
  for(const row of g.rows){
   const rowGroup=svg('g',{'data-map-theme':row.theme},region), parents=unique([...ancestors(row.theme)].map(id=>label(id)));
   const title=label(row.theme)+' · '+row.records.size+'/'+selection.recordIds.length;
   const titleWrap=lines(title,Math.max(6,Math.floor((w-pad*2)/15)));
   titleWrap.forEach((text,i)=>svg('text',{x:x+pad,y:bottom+15+i*21,fill:'#e4e7e8'},rowGroup,text));bottom+=titleWrap.length*21;
   if(parents.length){svg('title',{},rowGroup,'父主题：'+parents.join(' / ')+'；'+(summary.theme_definitions[row.theme]?.definition||''));}
   [...row.records.values()].forEach((r,index)=>{const px=x+pad+12+(index%perRow)*32,py=bottom+19+Math.floor(index/perRow)*34,states=unique(r.placements.map(state));
    const text=(r.facets.map(fid=>facet({record_id:r.record_id,facet_id:fid})?.interpretation).join('；')||words(r.record_id))+'；'+states.join('；')+'；原话：'+words(r.record_id);
    const a=svg('a',{href:r.facets.length?'#view-facet-'+encodeURIComponent(r.facets[0]):'#view-record-'+encodeURIComponent(r.record_id),'data-map-record':r.record_id,'data-map-region':g.id,'data-map-facets':r.facets.join(' '),'aria-label':text,...(selected===r.record_id?{'aria-current':'true'}:{})},rowGroup);
    svg('title',{},a,text);svg('circle',{cx:px,cy:py,r:6,fill:r.placements.length&&r.placements.every(p=>p.proposed_kind==='explicit'&&p.review_status!=='needs_review')?'#aeb9b8':'#17191a',stroke:selected===r.record_id?'#d5e8e2':'#aeb9b8','stroke-width':selected===r.record_id?2.5:1.6,...(r.placements.some(p=>p.review_status==='needs_review')?{'stroke-dasharray':'2 2'}:{})},a);
    if(selected===r.record_id)svg('circle',{cx:px,cy:py,r:11,fill:'none',stroke:'#d5e8e2','stroke-width':1},a);
    svg('circle',{cx:px,cy:py,r:15,fill:'transparent'},a);
    if(!exporting)a.onclick=e=>{e.preventDefault();e.stopPropagation();document.dispatchEvent(new CustomEvent('attention-map-select',{detail:{record_id:r.record_id,facet_ids:r.facets,region_id:g.id,theme_id:row.theme}}));};

   });
   bottom+=Math.ceil(row.records.size/perRow)*34+5;
   const stateRecords=new Map();for(const r of row.records.values())for(const text of unique(r.placements.map(state))){if(!stateRecords.has(text))stateRecords.set(text,new Set());stateRecords.get(text).add(r.record_id);}
   for(const line of lines([...stateRecords].map(([text,ids])=>text+' '+ids.size).join('；'),Math.max(6,Math.floor((w-pad*2)/13)))){svg('text',{x:x+pad,y:bottom+13,fill:'#b0b7b9','font-size':12},rowGroup,line);bottom+=18;}
   bottom+=16;
  }
  const height=bottom-y+8;
  if(isA){const boundary=svg('rect',{x:x+5,y:y-12,width:w-10,height:height+12,rx:Math.min(64,height/2),fill:'none',stroke:'#454c4f'},null);region.prepend(boundary);}
  else svg('line',{x1:x+pad,x2:x+w-pad,y1:y-12,y2:y-12,stroke:'#454c4f'},region);
  if(isA)ly=bottom+30;else if(hasA)ry=bottom+30;else ly=bottom+30;
 }
 let end=Math.max(ly,ry)+8;
 if(!selection.recordIds.length||!groups.some(g=>g.rows.some(r=>r.theme!=='@unprocessed'))){svg('text',{x:pad,y:end+15,fill:'#e4e7e8'},s,!selection.recordIds.length?'N=0 · 当前范围没有记录，无可计算比例':'当前条件零命中；分母仍为 '+selection.recordIds.length+' 条记录');end+=45;}
 const footer=['实心：明确对应；空心：其他或混合范围；虚线：含待核范围。具体关系与理由逐项见阅读区。',
  'A区域仅按本版条目组织；主题父子不重复画作同级。位置、面积、距离不表示权重。',
  ...(filters.length?['筛选：'+filters.join('；')]:['范围：全部记录与材料；全部表达属性']),
  ...(!selection.recordIds.length?['N=0：无比例。']:[])];
 for(const text of footer)for(const line of lines(text,Math.max(12,Math.floor((width-pad*2)/14)))){svg('text',{x:pad,y:end+18,fill:'#b0b7b9'},s,line);end+=21;}
 s.setAttribute('height',end+20);s.setAttribute('viewBox','0 0 '+width+' '+(end+20));return s;
}
function partGroups(index){
 const parts=new Map();
 for(const g of index.filter(g=>g.kind==='item')){
  const id='part:'+(g.part_id??'ungrouped');
  if(!parts.has(id))parts.set(id,{id,label:g.part,groups:[]});
  parts.get(id).groups.push(g);
 }
 return [...parts.values()];
}
function combinedRows(index){
 const themes=new Map();
 for(const group of index)for(const row of group.rows){
  if(!themes.has(row.theme))themes.set(row.theme,{theme:row.theme,records:new Map()});
  const dest=themes.get(row.theme).records;
  for(const [id,r] of row.records){
   if(!dest.has(id))dest.set(id,{record_id:id,facets:[],placements:[]});
   const record=dest.get(id);
   record.facets=unique([...record.facets,...r.facets]);
   record.placements.push(...r.placements);
  }
 }
 return [...themes.values()];
}
function bindMapLink(link, key, fn){
 link.dataset.mapKey=JSON.stringify(key);
 const select=e=>{e.preventDefault();e.stopPropagation();fn();};
 link.onclick=select;
 link.onkeydown=e=>{if(e.key==='Enter')select(e);};
}
function overview(width, exporting=false, index=groups){
 const parts=partGroups(index),hasA=parts.length>0;
 const sideBySide=hasA&&width>=760;
 const leftWidth=sideBySide?Math.round(width*.57):width;
 const radius=Math.floor(Math.min(exporting?245:Math.max(115,Math.min(205,(window.innerHeight-320)/2)),(leftWidth-36)/2));
 const cx=leftWidth/2,top=exporting?118:52,cy=top+radius;
 const right=sideBySide?leftWidth+16:18,rightWidth=width-right-18;
 const s=svg('svg',{xmlns:ns,width,role:exporting?'img':'group','aria-label':'B关注主题与同源记录 · 分母 '+selection.recordIds.length,'font-family':'Microsoft YaHei UI, Microsoft YaHei, sans-serif','font-size':14});
 svg('rect',{width:'100%',height:'100%',fill:'#17191a'},s);
 if(exporting){svg('text',{x:18,y:27,fill:'#e4e7e8','font-size':19},s,'B关注分布');svg('text',{x:18,y:51,fill:'#b0b7b9'},s,'当前筛选 · 分母 '+selection.recordIds.length+' 条评语记录 · 保存修订 '+summary.revision);svg('text',{x:18,y:73,fill:'#b0b7b9'},s,'A版本 '+(summary.a_version||'未导入')+' · 单位：记录并集；同源投影不可相加');}
 function activate(row,region,record){document.dispatchEvent(new CustomEvent('attention-map-select',{detail:{record_id:record.record_id,facet_ids:record.facets,region_id:region,theme_id:row.theme,cluster_records:[...row.records.values()].map(r=>({record_id:r.record_id,facet_ids:r.facets}))}}));}
 function cluster(row,x,y,region,maxWidth=180,parent=s){
  const selected=selection.selectedRecordId;
  const g=svg('g',{'data-map-theme':row.theme},parent),title=label(row.theme),titleLines=lines(title,Math.max(6,Math.floor(maxWidth/14))).slice(0,2);
  svg('title',{},g,title);
  if(titleLines.join('').length<title.length)titleLines[titleLines.length-1]=short(titleLines.at(-1),Array.from(titleLines.at(-1)).length-1);
  titleLines.forEach((t,i)=>svg('text',{x,y:y+i*18,'text-anchor':'middle',fill:'#e4e7e8'},g,t));
  svg('text',{x,y:y+titleLines.length*18,'text-anchor':'middle',fill:'#b0b7b9','font-size':12},g,row.records.size+'/'+selection.recordIds.length+' 条记录');
  const records=[...row.records.values()],shown=records.slice(0,8),spacing=22,cols=Math.min(4,shown.length),baseY=y+titleLines.length*18+19;
  shown.forEach((r,i)=>{const px=x-(cols-1)*spacing/2+(i%4)*spacing,py=baseY+Math.floor(i/4)*23,description=r.facets.map(fid=>facet({record_id:r.record_id,facet_id:fid})?.interpretation).join('；')||words(r.record_id);
   const a=svg('a',{href:r.facets.length?'#view-facet-'+encodeURIComponent(r.facets[0]):'#view-record-'+encodeURIComponent(r.record_id),'data-map-record':r.record_id,'data-map-region':region,'aria-label':description+'；'+unique(r.placements.map(state)).join('；'),...(selected===r.record_id?{'aria-current':'true'}:{})},g);
   svg('title',{},a,description+'；'+unique(r.placements.map(state)).join('；'));
   svg('circle',{cx:px,cy:py,r:5.5,fill:r.placements.length&&r.placements.every(p=>p.proposed_kind==='explicit'&&p.review_status!=='needs_review')?'#aeb9b8':'#17191a',stroke:selected===r.record_id?'#d5e8e2':'#aeb9b8','stroke-width':selected===r.record_id?2.4:1.6,...(r.placements.some(p=>p.review_status==='needs_review')?{'stroke-dasharray':'2 2'}:{})},a);
   if(selected===r.record_id)svg('circle',{cx:px,cy:py,r:9.5,fill:'none',stroke:'#d5e8e2'},a);svg('circle',{cx:px,cy:py,r:10.5,fill:'transparent'},a);
   if(!exporting)bindMapLink(a,[region,row.theme,r.record_id],()=>activate(row,region,r));
  });
  if(records.length>8){const a=svg('a',{href:'#focus-reading','aria-label':title+' · 展开全部 '+records.length+' 条记录'},g);svg('text',{x,y:baseY+48,'text-anchor':'middle',fill:'#d5e8e2','font-size':12},a,'查看全部 '+records.length+' 条');if(!exporting)bindMapLink(a,[region,row.theme,'all'],()=>activate(row,region,records[0]));}
  return baseY+Math.ceil(shown.length/4)*23+20;
 }
 let end=top;
 if(hasA){
  for(const part of parts){
   part.rows=combinedRows(part.groups).sort((a,b)=>Number(b.records.has(selection.selectedRecordId))-Number(a.records.has(selection.selectedRecordId))||b.records.size-a.records.size||label(a.theme).localeCompare(label(b.theme)));
  }
  const compact=parts.length<=3&&radius>=170&&parts.every(part=>Array.from(part.label).length<=7&&
    part.rows.length<=1&&part.rows.every(row=>row.records.size<=4&&Array.from(label(row.theme)).length<=7));
  const split=compact&&parts.length>1;
  svg('text',{x:cx,y:top-22,'text-anchor':'middle',fill:'#b0b7b9'},s,'本版A工作参照 · '+parts.length+' 个部分');
  const background=svg('g',{},s);
  if(compact&&!split)svg('circle',{cx,cy,r:radius,fill:'#1d2223',stroke:'#454c4f'},background);
  const plotWidth=leftWidth-24;
  const minRegionWidth=parts.some(part=>Array.from(part.label).length>12)?211:150;
  const regionColumns=parts.length<=3||width<620?1:Math.min(3,Math.max(1,Math.floor(plotWidth/minRegionWidth)));
  let rowTop=top,rowBottom=top,rowRegions=[];
  parts.forEach((part,i)=>{
   const {rows}=part;
   const region=svg('g',{'data-position-region':part.id,...(rows.some(r=>r.records.has(selection.selectedRecordId))?{'aria-current':'true'}:{})},s);
   svg('title',{},region,part.label);
   const empty=part.groups.every(g=>g.empty)?'尚无条目':'0/'+selection.recordIds.length+' 当前对应';
   if(!compact){
    const column=i%regionColumns,columnsInRow=Math.min(regionColumns,parts.length-i+column);
    const regionWidth=plotWidth/columnsInRow,x=12+column*regionWidth,pad=12,contentWidth=regionWidth-pad*2;
    const title=lines(part.label,Math.floor(contentWidth/13));
    title.forEach((line,j)=>svg('text',{x:x+pad,y:rowTop+22+j*19,fill:'#b0b7b9','font-size':13},region,line));
    let y=rowTop+21+title.length*19;
    const columns=Math.max(1,Math.min(rows.length,Math.floor(contentWidth/146)));
    const columnWidth=contentWidth/columns,slots=columns*2;
    const shown=rows.slice(0,slots);
    for(let start=0;start<shown.length;start+=columns){
     let bottom=y;
     shown.slice(start,start+columns).forEach((row,col)=>{
      const center=x+pad+(col+.5)*columnWidth;
      bottom=Math.max(bottom,cluster(row,center,y,part.id,columnWidth-10,region));
     });
     y=bottom;
    }
    if(!rows.length){svg('text',{x:x+pad,y,fill:'#b0b7b9','font-size':12},region,empty);y+=15;}
    if(rows.length>slots){
     const more=svg('a',{href:'#map-theme-select','aria-label':part.label+' · 查看其余 '+(rows.length-slots)+' 个主题'},region);
     svg('text',{x:x+pad,y,fill:'#d5e8e2','font-size':12},more,'另 '+(rows.length-slots)+' 主题');
     if(!exporting)bindMapLink(more,[part.id,'themes'],()=>document.getElementById('map-theme-select').focus());
     y+=15;
    }
    rowRegions.push({region,x});
    rowBottom=Math.max(rowBottom,y);
    if(rowRegions.length===columnsInRow){
     for(const area of rowRegions)area.region.prepend(svg('rect',{
      x:area.x,y:rowTop,width:regionWidth,height:rowBottom-rowTop,fill:'#1d2223',stroke:'#454c4f'}));
     rowRegions=[];
     rowTop=rowBottom;
    }
    return;
   }
   const n=parts.length,start=-Math.PI/2+i*2*Math.PI/n,finish=start+2*Math.PI/n,mid=(start+finish)/2;
   if(split)svg('path',{d:'M '+cx+' '+cy+' L '+(cx+radius*Math.cos(start))+' '+(cy+radius*Math.sin(start))+' A '+radius+' '+radius+' 0 '+(finish-start>Math.PI?1:0)+' 1 '+(cx+radius*Math.cos(finish))+' '+(cy+radius*Math.sin(finish))+' Z',fill:'#1d2223',stroke:'#454c4f'},background);
   const x=split?cx+Math.cos(mid)*radius*.54:cx;
   const titleY=split?cy+(n===3?(Math.sin(mid)>0?39:-74):-52):top+42;
   svg('text',{x,y:titleY,'text-anchor':'middle',fill:'#b0b7b9','font-size':13},region,part.label);
   const clusterY=titleY+(split?31:50);
   if(rows.length)cluster(rows[0],x,clusterY,part.id,116,region);
   else svg('text',{x,y:clusterY,'text-anchor':'middle',fill:'#b0b7b9','font-size':12},region,empty);
  });
  if(compact){
   svg('circle',{cx,cy,r:radius,fill:'none',stroke:'#697376','pointer-events':'none'},s);
   end=cy+radius+28;
  }else end=rowBottom+12;
 }
 let otherY=sideBySide?top:hasA?end+24:top;
 for(const group of index.filter(g=>g.kind!=='item')){
  const rows=group.rows;if(!rows.length)continue;
  const rg=svg('g',{'data-position-region':group.id,...(rows.some(r=>r.records.has(selection.selectedRecordId))?{'aria-current':'true'}:{})},s);
  const title=group.label+' · '+unique(rows.flatMap(r=>[...r.records.keys()])).length+'/'+selection.recordIds.length;
  const titleWrap=lines(title,Math.max(10,Math.floor(rightWidth/14)));titleWrap.forEach((t,i)=>svg('text',{x:right,y:otherY+i*19,fill:'#b0b7b9'},rg,t));otherY+=titleWrap.length*19+12;
  const available=Math.max(1,Math.floor(rightWidth/175)),columnWidth=rightWidth/available;
  rows.slice(0,available*2).forEach((row,i)=>{const x=right+(i%available+.5)*columnWidth,y=otherY+Math.floor(i/available)*118;cluster(row,x,y,group.id,Math.min(164,columnWidth-8));});
  otherY+=Math.ceil(Math.min(rows.length,available*2)/available)*118+10;
  if(rows.length>available*2){
   const text='另 '+(rows.length-available*2)+' 个主题';
   const more=svg('a',{href:'#map-theme-select','aria-label':text},rg);
   svg('text',{x:right,y:otherY,fill:'#d5e8e2','font-size':12},more,text);
   if(!exporting)bindMapLink(more,[group.id,'themes'],()=>document.getElementById('map-theme-select').focus());
   otherY+=28;
  }
 }
 end=Math.max(end,otherY)+16;
 if(!selection.recordIds.length||!index.some(g=>g.rows.some(r=>r.theme!=='@unprocessed'))){
  const message=!selection.recordIds.length?'N=0 · 无可计算比例':'当前条件零命中；分母仍为 '+selection.recordIds.length+' 条记录';
  for(const line of lines(message,Math.floor((width-36)/14))){svg('text',{x:18,y:end,fill:'#e4e7e8'},s,line);end+=20;}end+=8;
 }
 const notes=['每点一条记录 · 同源联动','实心：明确对应 · 空心：其他 · 虚线：含待核'];
 for(const note of notes)for(const line of lines(note,Math.max(15,Math.floor((width-36)/14)))){svg('text',{x:18,y:end,fill:'#b0b7b9','font-size':13},s,line);end+=20;}
 s.setAttribute('height',end+12);s.setAttribute('viewBox','0 0 '+width+' '+(end+12));
 if(exporting){const appendix=fullIndex(width,true),ah=Number(appendix.getAttribute('height'));const group=svg('g',{transform:'translate(0 '+(end+32)+')'},s);for(const child of [...appendix.children])if(child.tagName!=='rect')group.append(child);s.setAttribute('height',end+32+ah);s.setAttribute('viewBox','0 0 '+width+' '+(end+32+ah));}
 return s;
}
function download(type){
 const s=overview(1100,true,groups), content=new XMLSerializer().serializeToString(s), filename='B关注分布-修订'+summary.revision;
 const save=(blob,ext)=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename+ext;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 if(type==='svg'){save(new Blob([content],{type:'image/svg+xml;charset=utf-8'}),'.svg');return;}
 // data: is explicitly allowed by the page CSP for local SVG rasterization.
 const image=new Image();image.onload=()=>{const c=document.createElement('canvas');c.width=Number(s.getAttribute('width'));c.height=Number(s.getAttribute('height'));c.getContext('2d').drawImage(image,0,0);c.toBlob(b=>{if(b)save(b,'.png');else document.getElementById('map-export-status').textContent='PNG导出失败，请导出SVG。';});};
 image.onerror=()=>document.getElementById('map-export-status').textContent='PNG导出失败，请导出SVG。';image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(content);
}
function render(value,root){
 selection=value;mapRoot=root;
 const result=model(value);groups=result.groups;
 const active=document.activeElement,hadFocus=root.contains(active);
 const focusKey=active?.dataset?.mapKey,focusId=active?.id;
 const open=new Set([...root.querySelectorAll('details[open]')].map(d=>d.dataset.mapDetail));
 const scroll=root.querySelector('#attention-map')?.scrollTop||0;
 root.replaceChildren();
 html('h3','B关注分布',root);
 const controls=html('div',null,root,{class:'map-controls'}),aLabel=html('label',null,controls),toggle=html('input',null,aLabel,{type:'checkbox',id:'map-a-toggle'});
 toggle.checked=showA;toggle.disabled=!summary.a_reference.items.length&&!summary.a_reference.parts?.length;
 html('span','显示A工作参照',aLabel);
 toggle.onchange=()=>{showA=toggle.checked;render(selection,root);};
 const partChoices=partGroups(groups);
 if(!partChoices.some(p=>p.id===focusedPart))focusedPart='*';
 const partLabel=html('label','聚焦A部分',controls),partPick=html('select',null,partLabel,{id:'map-part-select'});
 html('option','全部A部分',partPick,{value:'*'});
 for(const p of partChoices)html('option',p.label,partPick,{value:p.id});
 partPick.value=focusedPart;partLabel.hidden=partChoices.length<2;
 partPick.onchange=()=>{focusedPart=partPick.value;render(selection,root);};
 const partScope=groups.filter(g=>focusedPart==='*'||g.kind!=='item'||'part:'+(g.part_id??'ungrouped')===focusedPart);
 const themesInScope=unique(partScope.flatMap(g=>g.rows.map(r=>r.theme)));
 const themeLabel=html('label','聚焦主题',controls),themePick=html('select',null,themeLabel,{id:'map-theme-select'});
 html('option','全部主题（概览）',themePick,{value:'*'});
 for(const id of themesInScope){
  const count=unique(partScope.flatMap(g=>g.rows.filter(r=>r.theme===id).flatMap(r=>[...r.records.keys()]))).length;
  html('option',label(id)+' · '+count+'/'+value.recordIds.length,themePick,{value:id});
 }
 if(!themesInScope.includes(focusedTheme))focusedTheme='*';
 themePick.value=focusedTheme;themePick.onchange=()=>{focusedTheme=themePick.value;render(selection,root);};
 for(const [type,text]of [['svg','导出 SVG'],['png','导出 PNG']]){
  const b=html('button',text,controls,{id:'export-map-'+type,type:'button',title:'导出全部当前筛选'});
  b.onclick=()=>download(type);
 }
 html('span','',controls,{id:'map-export-status',role:'status'});
 const visible=partScope.map(g=>({...g,rows:g.rows.filter(r=>focusedTheme==='*'||r.theme===focusedTheme)}));
 const detailLabel=partChoices.find(p=>p.id===focusedPart)?.label;
 const scopeLabel=[detailLabel?'A部分 '+detailLabel:'',focusedTheme!=='*'?'主题 '+label(focusedTheme):''].filter(Boolean).join(' · ');
 const hits=unique(visible.flatMap(g=>g.rows.filter(r=>r.theme!=='@unprocessed').flatMap(r=>[...r.records.keys()]))).length;
 html('p',(scopeLabel?'视图聚焦 · '+scopeLabel:'当前筛选')+' · 分母 '+value.recordIds.length+' 条记录 · '+hits+'/'+value.recordIds.length+' 条记录有解释',root,{id:'map-scope'});
 const wrap=html('div',null,root,{id:'attention-map',tabindex:'0','aria-label':'关注图'});
 wrap.append(overview(Math.max(220,Math.floor(wrap.clientWidth||760)),false,visible));
 wrap.scrollTop=scroll;
 // The complete drill uses the same view focus; export always includes all filtered rows.
 const drill=html('details',null,root,{id:'position-drill','data-map-detail':'all'});
 drill.open=open.has('all');
 html('summary','本视图的位置与主题明细',drill,{'data-map-key':'drill'});
 for(const g of visible){
  const section=html('details',null,drill,{'data-map-detail':g.id});section.open=open.has(g.id);
  html('summary',g.label,section,{'data-map-key':JSON.stringify(['detail',g.id])});
  for(const row of g.rows){
   html('h4',label(row.theme)+' · '+row.records.size+'/'+value.recordIds.length,section);
   for(const r of row.records.values()){
    const li=html('div',null,section);
    for(const fid of r.facets)html('a',facet({record_id:r.record_id,facet_id:fid})?.interpretation,li,{href:'#view-facet-'+encodeURIComponent(fid),'data-map-key':JSON.stringify(['detail',g.id,row.theme,fid])});
    if(!r.facets.length)html('a',short(words(r.record_id),60),li,{href:'#view-record-'+encodeURIComponent(r.record_id),'data-map-key':JSON.stringify(['detail',g.id,row.theme,r.record_id])});
    for(const p of r.placements)html('p',state(p)+' · '+p.scope+' · '+p.reason,li);
   }
  }
 }
 if(hadFocus){
  const target=(focusId&&root.querySelector('#'+CSS.escape(focusId)))||
      (focusKey&&root.querySelector('[data-map-key="'+CSS.escape(focusKey)+'"]'));
  (target||themePick).focus({preventScroll:true});
 }
}
let resizeFrame;
window.addEventListener('resize',()=>{
 cancelAnimationFrame(resizeFrame);
 resizeFrame=requestAnimationFrame(()=>{if(mapRoot?.offsetWidth&&selection)render(selection,mapRoot);});
});
window.AttentionMap=Object.freeze({render});
})();
